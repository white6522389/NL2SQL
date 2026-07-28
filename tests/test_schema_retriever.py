from vanna.agents.nl2sql import SchemaCatalog, SchemaColumn, SchemaTable
from vanna.services import MySQLSchemaRepository, SchemaRetriever


def sample_catalog():
    return SchemaCatalog(
        database="ssss",
        tables=[
            SchemaTable(
                name="orders",
                comment="销售订单",
                columns=[
                    SchemaColumn(name="amount", data_type="decimal(10,2)", comment="销售额"),
                    SchemaColumn(name="region", data_type="varchar(50)", comment="销售地区"),
                    SchemaColumn(
                        name="product_id",
                        data_type="bigint",
                        comment="商品编号",
                        referenced_table="products",
                        referenced_column="id",
                    ),
                ],
            ),
            SchemaTable(
                name="products",
                comment="商品",
                columns=[
                    SchemaColumn(name="id", data_type="bigint", key="PRI"),
                    SchemaColumn(name="name", data_type="varchar(100)", comment="商品名称"),
                ],
            ),
            SchemaTable(name="employees", comment="员工信息"),
        ],
    )


def test_retrieves_sales_tables_and_fk_relation():
    context = SchemaRetriever(sample_catalog()).retrieve("查询华东销售额最高商品", top_k=1)

    assert [table.name for table in context.tables] == ["orders", "products"]
    assert "FK -> products.id" in context.as_prompt()


def test_schema_prompt_includes_actual_business_values():
    catalog = sample_catalog()
    catalog.tables[0].columns[1].sample_values = ["华东", "华南", "华北"]

    prompt = SchemaRetriever(catalog).retrieve("查询华东销售额").as_prompt()

    assert "actual values: '华东', '华南', '华北'" in prompt


class FakeCursor:
    def __init__(self):
        self.query_index = 0

    def execute(self, query, params):
        assert params == ("ssss",)
        self.query_index += 1

    def fetchall(self):
        if self.query_index == 1:
            return [{"TABLE_NAME": "orders", "TABLE_COMMENT": "销售订单"}]
        return [
            {
                "TABLE_NAME": "orders",
                "COLUMN_NAME": "id",
                "COLUMN_TYPE": "bigint",
                "IS_NULLABLE": "NO",
                "COLUMN_KEY": "PRI",
                "COLUMN_COMMENT": "订单编号",
                "REFERENCED_TABLE_NAME": None,
                "REFERENCED_COLUMN_NAME": None,
            }
        ]

    def close(self):
        pass


class FakeConnection:
    def __init__(self):
        self.cursor_instance = FakeCursor()
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def close(self):
        self.closed = True


def test_repository_builds_catalog_from_information_schema():
    connection = FakeConnection()
    catalog = MySQLSchemaRepository("ssss", lambda: connection).load()

    assert catalog.database == "ssss"
    assert catalog.tables[0].name == "orders"
    assert catalog.tables[0].columns[0].key == "PRI"
    assert catalog.tables[0].columns[0].nullable is False
    assert connection.closed is True


def test_only_safe_categorical_columns_are_sampled():
    assert MySQLSchemaRepository._is_safe_categorical_column("region", "varchar(50)")
    assert MySQLSchemaRepository._is_safe_categorical_column("status", "char(1)")
    assert MySQLSchemaRepository._is_safe_categorical_column("anything", "enum('a','b')")
    assert not MySQLSchemaRepository._is_safe_categorical_column(
        "customer_name", "varchar(100)"
    )
    assert not MySQLSchemaRepository._is_safe_categorical_column(
        "email", "varchar(255)"
    )
