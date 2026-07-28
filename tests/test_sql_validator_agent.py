import pytest

from vanna.agents.nl2sql import (
    SQLValidatorAgent,
    SchemaCatalog,
    SchemaColumn,
    SchemaTable,
)


@pytest.fixture
def schema():
    return SchemaCatalog(
        database="ssss",
        tables=[
            SchemaTable(
                name="orders",
                columns=[
                    SchemaColumn(name="id", data_type="bigint"),
                    SchemaColumn(name="amount", data_type="decimal(10,2)"),
                    SchemaColumn(name="product_id", data_type="bigint"),
                    SchemaColumn(
                        name="region",
                        data_type="varchar(50)",
                        sample_values=["华东", "华南", "华北", "华中"],
                    ),
                ],
            ),
            SchemaTable(
                name="products",
                columns=[
                    SchemaColumn(name="id", data_type="bigint"),
                    SchemaColumn(name="name", data_type="varchar(100)"),
                ],
            ),
        ],
    )


@pytest.mark.parametrize("sql", [
    "DROP TABLE orders",
    "DELETE FROM orders",
    "UPDATE orders SET amount = 0",
    "SELECT * FROM orders; DROP TABLE orders",
])
def test_rejects_dangerous_or_multiple_statements(schema, sql):
    result = SQLValidatorAgent().validate(sql, schema)
    assert result.valid is False


def test_accepts_valid_join(schema):
    sql = (
        "SELECT p.name, SUM(o.amount) FROM orders o "
        "JOIN products p ON p.id = o.product_id GROUP BY p.name"
    )
    result = SQLValidatorAgent().validate(sql, schema)
    assert result.valid is True
    assert result.referenced_tables == ["orders", "products"]


def test_rejects_unknown_table(schema):
    result = SQLValidatorAgent().validate("SELECT x.id FROM missing x", schema)
    assert result.valid is False
    assert result.reason == "表不存在: missing"


def test_rejects_unknown_qualified_column(schema):
    result = SQLValidatorAgent().validate("SELECT o.sales FROM orders o", schema)
    assert result.valid is False
    assert result.reason == "字段不存在: orders.sales"


def test_detects_basic_syntax_shape_error(schema):
    result = SQLValidatorAgent().validate("SELECT * FORM orders", schema)
    assert result.valid is False
    assert "FROM" in result.reason


def test_rejects_unknown_categorical_value_with_correction(schema):
    result = SQLValidatorAgent().validate(
        "SELECT o.amount FROM orders o WHERE o.region = 'East China'", schema
    )

    assert result.valid is False
    assert result.error_type == "invalid_enum_value"
    assert "华东" in result.suggestion


def test_accepts_real_chinese_categorical_value(schema):
    result = SQLValidatorAgent().validate(
        "SELECT o.amount FROM orders o WHERE o.region = '华东'", schema
    )

    assert result.valid is True


def test_rejects_cross_join(schema):
    result = SQLValidatorAgent().validate(
        "SELECT o.amount FROM orders o CROSS JOIN products p", schema
    )

    assert result.valid is False
    assert result.error_type == "unsafe_join"
