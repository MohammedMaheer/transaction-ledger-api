"""Create accounts and immutable-through-API ledger entries.

Revision ID: 0001
Revises: None
"""

import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("balance", sa.Numeric(18, 2), server_default=sa.text("0.00"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_accounts"),
        sa.CheckConstraint(
            "balance >= 0 AND balance <> 'NaN'::numeric",
            name=op.f("ck_accounts_balance_nonnegative"),
        ),
        sa.CheckConstraint("length(trim(name)) > 0", name=op.f("ck_accounts_name_not_blank")),
    )
    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(6), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("reference_id", sa.String(100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_transactions"),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name="fk_transactions_account_id_accounts"
        ),
        sa.UniqueConstraint("account_id", "reference_id", name="uq_transactions_account_reference"),
        sa.CheckConstraint(
            "amount > 0 AND amount <> 'NaN'::numeric", name=op.f("ck_transactions_amount_positive")
        ),
        sa.CheckConstraint("type IN ('credit', 'debit')", name=op.f("ck_transactions_type_valid")),
        sa.CheckConstraint(
            "length(trim(reference_id)) > 0", name=op.f("ck_transactions_reference_not_blank")
        ),
    )
    op.create_index(
        "ix_transactions_account_created_id",
        "transactions",
        ["account_id", sa.text("created_at DESC"), sa.text("id DESC")],
    )


def downgrade():
    op.drop_index("ix_transactions_account_created_id", table_name="transactions")
    op.drop_table("transactions")
    op.drop_table("accounts")
