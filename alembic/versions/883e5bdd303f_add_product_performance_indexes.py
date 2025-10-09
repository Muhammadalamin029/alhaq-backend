"""add_product_performance_indexes

Revision ID: 883e5bdd303f
Revises: 6ab1b7df42a5
Create Date: 2025-10-09 23:47:19.731031

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '883e5bdd303f'
down_revision = '6ab1b7df42a5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add indexes for product performance optimization
    op.create_index('ix_products_seller_id', 'products', ['seller_id'])
    op.create_index('ix_products_category_id', 'products', ['category_id'])
    op.create_index('ix_products_status', 'products', ['status'])
    op.create_index('ix_products_created_at', 'products', ['created_at'])
    op.create_index('ix_products_price', 'products', ['price'])
    op.create_index('ix_products_stock_quantity', 'products', ['stock_quantity'])
    
    # Add composite indexes for common query patterns
    op.create_index('ix_products_status_created_at', 'products', ['status', 'created_at'])
    op.create_index('ix_products_category_status', 'products', ['category_id', 'status'])
    op.create_index('ix_products_seller_status', 'products', ['seller_id', 'status'])
    
    # Add text search index for product names (for search functionality)
    op.execute('CREATE INDEX ix_products_name_gin ON products USING gin(to_tsvector(\'english\', name))')


def downgrade() -> None:
    # Drop indexes in reverse order
    op.execute('DROP INDEX IF EXISTS ix_products_name_gin')
    op.drop_index('ix_products_seller_status', table_name='products')
    op.drop_index('ix_products_category_status', table_name='products')
    op.drop_index('ix_products_status_created_at', table_name='products')
    op.drop_index('ix_products_stock_quantity', table_name='products')
    op.drop_index('ix_products_price', table_name='products')
    op.drop_index('ix_products_created_at', table_name='products')
    op.drop_index('ix_products_status', table_name='products')
    op.drop_index('ix_products_category_id', table_name='products')
    op.drop_index('ix_products_seller_id', table_name='products')
