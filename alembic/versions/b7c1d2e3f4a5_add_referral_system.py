"""add referral campaign system

Revision ID: b7c1d2e3f4a5
Revises: f8a9b0c1d2e3
Create Date: 2026-11-02 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "b7c1d2e3f4a5"
down_revision = "f8a9b0c1d2e3"
branch_labels = None
depends_on = None


participation_status = postgresql.ENUM(
    "active", "qualified", "rewarded", "cancelled",
    name="referral_participation_status", create_type=False,
)
referral_status = postgresql.ENUM(
    "pending", "confirmed", "rejected", "expired",
    name="referral_status", create_type=False,
)
claim_status = postgresql.ENUM(
    "unlocked", "awarded", "order_created", "fulfilled", "cancelled",
    name="referral_claim_status", create_type=False,
)
order_type = postgresql.ENUM(
    "standard", "referral_reward",
    name="order_type", create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()

    participation_status.create(bind, checkfirst=True)
    referral_status.create(bind, checkfirst=True)
    claim_status.create(bind, checkfirst=True)
    order_type.create(bind, checkfirst=True)

    op.create_table(
        "referral_campaigns",
        sa.Column("id", sa.UUID(), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("required_referrals", sa.Integer(), nullable=False,
                  server_default="1"),
        sa.Column("start_at", sa.TIMESTAMP(), nullable=False),
        sa.Column("end_at", sa.TIMESTAMP(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        sa.Column("ended_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("customer_pays_delivery", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("terms_locked_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("max_credited_referrals_per_device", sa.Integer(),
                  nullable=False, server_default="1"),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=True,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=True,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_referral_campaigns_id", "referral_campaigns", ["id"])
    op.create_index("ix_referral_campaigns_is_active", "referral_campaigns",
                    ["is_active"])
    op.create_index("ix_referral_campaigns_start_at", "referral_campaigns",
                    ["start_at"])
    op.create_index("ix_referral_campaigns_end_at", "referral_campaigns",
                    ["end_at"])

    op.create_table(
        "referral_campaign_products",
        sa.Column("id", sa.UUID(), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("campaign_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=True,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["campaign_id"], ["referral_campaigns.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"],
                                ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("campaign_id", "product_id",
                            name="uq_referral_campaign_product"),
    )
    op.create_index("ix_referral_campaign_products_id",
                    "referral_campaign_products", ["id"])
    op.create_index("ix_referral_campaign_products_campaign_id",
                    "referral_campaign_products", ["campaign_id"])

    op.create_table(
        "referral_participations",
        sa.Column("id", sa.UUID(), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("campaign_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("referral_code", sa.String(length=16), nullable=False),
        sa.Column("status", participation_status, nullable=False,
                  server_default="active"),
        sa.Column("qualified_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=True,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=True,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["campaign_id"], ["referral_campaigns.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("campaign_id", "user_id",
                            name="uq_referral_participation_user"),
    )
    op.create_index("ix_referral_participations_id",
                    "referral_participations", ["id"])
    op.create_index("ix_referral_participations_campaign_id",
                    "referral_participations", ["campaign_id"])
    op.create_index("ix_referral_participations_user_id",
                    "referral_participations", ["user_id"])
    op.create_index("ix_referral_participations_referral_code",
                    "referral_participations", ["referral_code"], unique=True)

    op.create_table(
        "referrals",
        sa.Column("id", sa.UUID(), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("participation_id", sa.UUID(), nullable=False),
        sa.Column("campaign_id", sa.UUID(), nullable=False),
        sa.Column("referrer_user_id", sa.UUID(), nullable=False),
        sa.Column("referred_user_id", sa.UUID(), nullable=False),
        sa.Column("code_used", sa.String(length=16), nullable=False),
        sa.Column("status", referral_status, nullable=False,
                  server_default="pending"),
        sa.Column("device_hash", sa.String(length=64), nullable=True),
        sa.Column("signup_ip_hash", sa.String(length=64), nullable=True),
        sa.Column("rejection_reason", sa.String(length=120), nullable=True),
        sa.Column("registered_at", sa.TIMESTAMP(), nullable=True,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("confirmed_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=True,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=True,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["participation_id"],
                                ["referral_participations.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campaign_id"], ["referral_campaigns.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["referrer_user_id"], ["users.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["referred_user_id"], ["users.id"],
                                ondelete="CASCADE"),
        sa.CheckConstraint("referrer_user_id <> referred_user_id",
                           name="ck_referral_no_self_referral"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("referred_user_id", name="uq_referral_referred_user"),
    )
    op.create_index("ix_referrals_id", "referrals", ["id"])
    op.create_index("ix_referrals_participation_id", "referrals",
                    ["participation_id"])
    op.create_index("ix_referrals_campaign_id", "referrals", ["campaign_id"])
    op.create_index("ix_referrals_referrer_user_id", "referrals",
                    ["referrer_user_id"])
    op.create_index("ix_referrals_referred_user_id", "referrals",
                    ["referred_user_id"])
    op.create_index("ix_referrals_device_hash", "referrals", ["device_hash"])

    op.create_table(
        "referral_reward_claims",
        sa.Column("id", sa.UUID(), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("participation_id", sa.UUID(), nullable=False),
        sa.Column("campaign_id", sa.UUID(), nullable=False),
        sa.Column("status", claim_status, nullable=False,
                  server_default="unlocked"),
        sa.Column("won_product_id", sa.UUID(), nullable=True),
        sa.Column("wheel_snapshot", sa.JSON(), nullable=True),
        sa.Column("segment_index", sa.Integer(), nullable=True),
        sa.Column("draw_nonce", sa.String(length=64), nullable=True),
        sa.Column("awarded_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=True,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=True,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["participation_id"],
                                ["referral_participations.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campaign_id"], ["referral_campaigns.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["won_product_id"], ["products.id"],
                                ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("participation_id",
                            name="uq_referral_claim_participation"),
    )
    op.create_index("ix_referral_reward_claims_id",
                    "referral_reward_claims", ["id"])
    op.create_index("ix_referral_reward_claims_participation_id",
                    "referral_reward_claims", ["participation_id"])
    op.create_index("ix_referral_reward_claims_campaign_id",
                    "referral_reward_claims", ["campaign_id"])

    op.create_table(
        "referral_events",
        sa.Column("id", sa.UUID(), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("event", sa.String(length=64), nullable=False),
        sa.Column("campaign_id", sa.UUID(), nullable=True),
        sa.Column("participation_id", sa.UUID(), nullable=True),
        sa.Column("referral_id", sa.UUID(), nullable=True),
        sa.Column("claim_id", sa.UUID(), nullable=True),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=True,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["campaign_id"], ["referral_campaigns.id"],
                                ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["participation_id"],
                                ["referral_participations.id"],
                                ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["referral_id"], ["referrals.id"],
                                ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["claim_id"], ["referral_reward_claims.id"],
                                ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"],
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_referral_events_id", "referral_events", ["id"])
    op.create_index("ix_referral_events_event", "referral_events", ["event"])
    op.create_index("ix_referral_events_campaign_id", "referral_events",
                    ["campaign_id"])
    op.create_index("ix_referral_events_participation_id", "referral_events",
                    ["participation_id"])

    op.add_column(
        "orders",
        sa.Column("order_type", order_type, nullable=False,
                  server_default="standard"),
    )
    op.add_column(
        "orders",
        sa.Column("referral_claim_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_orders_referral_claim_id",
        "orders",
        "referral_reward_claims",
        ["referral_claim_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_orders_referral_claim_id", "orders", ["referral_claim_id"]
    )
    op.create_index("ix_orders_order_type", "orders", ["order_type"])

    # New notification types. ALTER TYPE ... ADD VALUE is idempotent here and
    # safe on PostgreSQL 12+ inside the migration transaction.
    for value in (
        "referral_confirmed",
        "referral_qualified",
        "referral_reward_awarded",
        "referral_order_created",
    ):
        op.execute(
            f"ALTER TYPE notification_type ADD VALUE IF NOT EXISTS '{value}'"
        )


def downgrade() -> None:
    op.drop_index("ix_orders_order_type", table_name="orders")
    op.drop_constraint("uq_orders_referral_claim_id", "orders", type_="unique")
    op.drop_constraint("fk_orders_referral_claim_id", "orders", type_="foreignkey")
    op.drop_column("orders", "referral_claim_id")
    op.drop_column("orders", "order_type")

    op.drop_table("referral_events")
    op.drop_table("referral_reward_claims")
    op.drop_table("referrals")
    op.drop_table("referral_participations")
    op.drop_table("referral_campaign_products")
    op.drop_table("referral_campaigns")

    bind = op.get_bind()
    claim_status.drop(bind, checkfirst=True)
    referral_status.drop(bind, checkfirst=True)
    participation_status.drop(bind, checkfirst=True)
    order_type.drop(bind, checkfirst=True)
