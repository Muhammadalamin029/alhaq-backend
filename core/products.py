from core.model import Product, AssetImage
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import UUID, and_, case, func, literal, or_
from schemas.media import AssetImageResponse
from typing import Optional

# Trigram similarity floor for fuzzy matching. Short queries (< 3 chars)
# skip the fuzzy branch entirely — trigram scores are meaningless there.
FUZZY_MIN_QUERY_LEN = 3
FUZZY_SIMILARITY_THRESHOLD = 0.25
FUZZY_WORD_SIMILARITY_THRESHOLD = 0.35


def _like_escape(value: str) -> str:
    """Escape LIKE wildcards so user input matches literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class ProductService:
    def _with_relationships(self, query):
        """Helper to always eager-load seller, category, and images"""
        return query.options(
            joinedload(Product.seller),
            joinedload(Product.category),
            joinedload(Product.images)
        )

    def fetch_products(self, db: Session, search_query: Optional[str] = None, category_id: Optional[str] = None, limit: int = 10, page: int = 1,
                       min_price: Optional[float] = None, max_price: Optional[float] = None, status: Optional[str] = None,
                       sort_by: Optional[str] = None, sort_order: Optional[str] = None):

        from core.discounts import effective_price_expr
        query = self._with_relationships(db.query(Product))

        # Filter by status (defaults to active-only for storefront)
        query = query.filter(Product.status == (status or "active"))

        if category_id:
            query = query.filter(Product.category_id == category_id)

        # Sale-aware price filtering (uses effective/discounted price)
        sale_price = effective_price_expr(Product)
        if min_price is not None:
            query = query.filter(sale_price >= min_price)

        if max_price is not None:
            query = query.filter(sale_price <= max_price)

        if search_query:
            normalized = " ".join(search_query.split())
            if normalized:
                lowered = normalized.lower()
                tokens = lowered.split(" ")
                name_col = func.lower(Product.name)
                desc_col = func.lower(func.coalesce(Product.description, ""))

                # Every token must appear in the name or description
                # (substring match, wildcards escaped).
                token_clauses = [
                    or_(
                        Product.name.ilike(
                            f"%{_like_escape(t)}%", escape="\\"
                        ),
                        Product.description.ilike(
                            f"%{_like_escape(t)}%", escape="\\"
                        ),
                    )
                    for t in tokens
                ]

                # Typo-tolerant fallback: trigram similarity against the full
                # query catches transpositions/misspellings the token match
                # misses (e.g. "snekers" vs "sneakers").
                match_clauses = [and_(*token_clauses)]
                if len(lowered) >= FUZZY_MIN_QUERY_LEN:
                    match_clauses.append(
                        or_(
                            func.similarity(name_col, lowered)
                            > FUZZY_SIMILARITY_THRESHOLD,
                            func.word_similarity(literal(lowered), name_col)
                            > FUZZY_WORD_SIMILARITY_THRESHOLD,
                            func.similarity(desc_col, lowered)
                            > FUZZY_SIMILARITY_THRESHOLD,
                        )
                    )
                query = query.filter(or_(*match_clauses))

                # Rank: exact name > substring of full query > trigram
                # similarity. Applied first; the sort_by below tie-breaks.
                rank = (
                    case((name_col == lowered, 100), else_=0)
                    + case(
                        (
                            Product.name.ilike(
                                f"%{_like_escape(lowered)}%",
                                escape="\\",
                            ),
                            50,
                        ),
                        else_=0,
                    )
                    + (func.similarity(name_col, literal(lowered)) * 30)
                    + (
                        func.word_similarity(literal(lowered), name_col)
                        * 20
                    )
                )
                query = query.order_by(rank.desc())

        # Ordering — strict whitelist so arbitrary column names can't reach order_by
        # "price" sorts/filters on the sale-aware effective price.
        from core.discounts import effective_price_expr as _eff_expr
        sortable = {"created_at": Product.created_at, "price": _eff_expr(Product), "name": Product.name}
        sort_column = sortable.get((sort_by or "created_at").lower(), Product.created_at)
        if (sort_order or "desc").lower() == "asc":
            query = query.order_by(sort_column.asc())
        else:
            query = query.order_by(sort_column.desc())

        offset = (page - 1) * limit
        count = query.count()
        products = query.offset(offset).limit(limit).all()
        return products, count

    def add_product(
        self,
        db: Session,
        name: str,
        price: float,
        user_id: UUID,
        category_id: UUID,
        description: Optional[str] = None,
        stock_quantity: int = 0,
        amenities: Optional[list] = None,
        images: Optional[list] = None,
        discount_percent: Optional[float] = None,
        sale_price: Optional[float] = None,
        discount_starts_at=None,
        discount_ends_at=None,
    ):
        from core.discounts import normalize_discount, validate_window
        pct = normalize_discount(price, discount_percent, sale_price) if (discount_percent not in (None, "") or sale_price not in (None, "")) else None
        validate_window(discount_starts_at, discount_ends_at)
        if pct is None and (discount_starts_at is not None or discount_ends_at is not None):
            raise ValueError("Discount dates require a discount percent or sale price")
        # 1. Create product with default status
        new_product = Product(
            name=name,
            price=price,
            seller_id=user_id,
            category_id=category_id,
            description=description,
            stock_quantity=stock_quantity,
            amenities=amenities or [],
            discount_percent=float(pct) if pct is not None else None,
            discount_starts_at=discount_starts_at,
            discount_ends_at=discount_ends_at,
            status="active" if stock_quantity > 0 else "out_of_stock"
        )
        db.add(new_product)
        db.flush()  # assign ID

        # 2. Add images if provided
        if images:
            for img in images:
                product_image = AssetImage(
                    product_id=new_product.id,
                    image_url=img.image_url
                )
                db.add(product_image)

        db.commit()
        db.refresh(new_product)

        # 3. Eager load relationships for response
        return db.query(Product).options(
            joinedload(Product.seller),
            joinedload(Product.category),
            joinedload(Product.images)
        ).filter(Product.id == new_product.id).first()

    def get_product_by_id(self, db: Session, product_id: UUID):
        return (
            self._with_relationships(db.query(Product))
            .filter(Product.id == product_id)
            .first()
        )

    def get_products_by_seller(
        self, db: Session, seller_id: UUID, limit: int = 10, page: int = 1
    ):
        query = self._with_relationships(db.query(Product)).filter(
            Product.seller_id == seller_id
        )

        count = query.count()
        offset = (page - 1) * limit

        products = query.offset(offset).limit(limit).all()

        return products, count

    def update_product_stock(self, db: Session, product_id: UUID, new_stock: int):
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            return None
        product.stock_quantity = new_stock
        db.commit()
        db.refresh(product)
        return self.get_product_by_id(db, product.id)

    def delete_product(self, db: Session, product_id: UUID):
        from core.logging_config import get_logger
        logger = get_logger(__name__)
        
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            logger.warning(f"Product {product_id} not found for deletion")
            return False
        
        # Check if product has any order items (financial records)
        from core.model import OrderItem
        existing_order_items = db.query(OrderItem).filter(OrderItem.product_id == product_id).first()
        
        if existing_order_items:
            # If product has order history, mark as inactive instead of deleting
            logger.info(f"Product {product_id} has order history, marking as inactive instead of deleting")
            product.status = "inactive"
            product.name = f"[DELETED] {product.name}"  # Mark as deleted for reference
            db.commit()
            db.refresh(product)
            return True
        else:
            # Safe to delete - no order history
            logger.info(f"Product {product_id} has no order history, proceeding with deletion")
            db.delete(product)
            db.commit()
            return True

    def update_product(self, db: Session, product_id: UUID, **kwargs):
        from core.logging_config import get_logger
        logger = get_logger(__name__)
        
        logger.info(f"update_product called with product_id: {product_id}, kwargs: {kwargs}")
        
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            logger.error(f"Product {product_id} not found")
            return None

        from core.discounts import normalize_discount, validate_window

        # --- Discount handling (percent and/or sale price; sale_price wins) ---
        sale_price_input = kwargs.pop("sale_price", None)
        discount_pct_input = kwargs.pop("discount_percent", None)
        clear_discount = kwargs.pop("clear_discount", None)
        starts_input = kwargs.pop("discount_starts_at", None) if "discount_starts_at" in kwargs else "__keep__"
        ends_input = kwargs.pop("discount_ends_at", None) if "discount_ends_at" in kwargs else "__keep__"
        discount_touched = (
            sale_price_input not in (None, "")
            or discount_pct_input not in (None, "")
            or starts_input != "__keep__"
            or ends_input != "__keep__"
            or clear_discount
        )
        if discount_touched:
            new_starts = product.discount_starts_at if starts_input == "__keep__" else starts_input
            new_ends = product.discount_ends_at if ends_input == "__keep__" else ends_input
            if clear_discount and sale_price_input in (None, "") and discount_pct_input in (None, "") and starts_input == "__keep__" and ends_input == "__keep__":
                product.discount_percent = None
                product.discount_starts_at = None
                product.discount_ends_at = None
                logger.info("Cleared discount")
            else:
                base_price = kwargs.get("price", product.price)
                if sale_price_input not in (None, "") or discount_pct_input not in (None, ""):
                    pct = normalize_discount(base_price, discount_pct_input, sale_price_input)
                else:
                    pct = product.discount_percent
                    if pct is None and (new_starts is not None or new_ends is not None):
                        raise ValueError("Discount dates require a discount percent or sale price")
                # Explicit zero percent removes the sale but keeps window cleared
                if discount_pct_input == 0 and sale_price_input in (None, ""):
                    product.discount_percent = None
                    product.discount_starts_at = None
                    product.discount_ends_at = None
                else:
                    validate_window(new_starts, new_ends)
                    product.discount_percent = float(pct) if pct is not None else None
                    product.discount_starts_at = new_starts
                    product.discount_ends_at = new_ends
            # If only the base price changed while a sale is active, keep pct as-is
            # (effective price derives automatically).
            
        logger.info(f"Found product: {product.name} (ID: {product.id})")
        
        # Handle images separately if present
        if "images" in kwargs:
            logger.info(f"Updating images for product {product_id}")
            images_data = kwargs.pop("images")
            
            # Remove existing images
            db.query(AssetImage).filter(AssetImage.product_id == product_id).delete()
            
            # Add new images
            if images_data:
                for img_data in images_data:
                    image_url = img_data["image_url"] if isinstance(img_data, dict) else img_data.image_url
                    new_image = AssetImage(
                        product_id=product_id,
                        image_url=image_url
                    )
                    db.add(new_image)
        
        for key, value in kwargs.items():
            old_value = getattr(product, key, None)
            setattr(product, key, value)
            logger.info(f"Updated {key}: {old_value} -> {value}")
            
        logger.info("Committing changes to database...")
        try:
            db.commit()
            db.refresh(product)
            logger.info(f"Product updated successfully: {product.name}")
            return self.get_product_by_id(db, product.id)
        except Exception as commit_error:
            logger.error(f"Error committing product update: {str(commit_error)}")
            db.rollback()
            raise commit_error


product_service = ProductService()
