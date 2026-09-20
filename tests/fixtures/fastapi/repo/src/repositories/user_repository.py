from sqlalchemy.orm import Mapped, mapped_column


class User:
    id: Mapped[int] = mapped_column(primary_key=True)


def to_schema(schema, row):
    return schema.model_validate(row).model_dump()
