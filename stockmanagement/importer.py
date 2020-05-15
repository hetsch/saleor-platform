import sqlite3
import json
from pathlib import Path

from saleor.product import models
from saleor.product.utils.attributes import generate_name_for_variant
from saleor.warehouse import models as wm
from saleor.account import models as am
from saleor.shipping import models as sm
from django_countries.data import COUNTRIES
from django.db import connection
from django.utils.text import slugify


# To execute the script, call it with:
# docker-compose exec web ./manage.py shell --command="from importer.stockmanagement import run; run()"


product_type_map = {}
product_map = {}
attribute_map = {}
attribute_value_map = {}


DB_PATH = Path().resolve().joinpath("stockmanagement", "stockmanagement.db")


def dictfetchall(cursor):
    "Return all rows from a cursor as a dict"
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def get_or_create_attribute_value(name, attribute, slug=None, sort_order=0):
    slug = slug or slugify(name)
    obj, created = models.AttributeValue.objects.get_or_create(
        name=name, slug=slug, attribute=attribute, sort_order=sort_order
    )
    if created:
        obj.sort_order = sort_order
        obj.save(update_fields=["sort_order"])
    return obj


def run():
    print("[+] RUNNING IMPORTER")
    with sqlite3.connect(DB_PATH) as db:
        c = db.cursor()

        # -----------------------------------------------------------------------
        # P R O D U C T   T Y P E S
        # -----------------------------------------------------------------------

        for row in dictfetchall(c.execute("SELECT * FROM products_productclass")):
            product_type, _ = models.ProductType.objects.get_or_create(
                name=row["name"], slug=slugify(row["name"]), has_variants=bool(row["has_variants"])
            )
            product_type_map[int(row["id"])] = product_type

            # Create all product specific attributes for that ProductType
            attr_ids = [
                x[0]
                for x in c.execute(
                    "SELECT productattribute_id "
                    "FROM products_productclass_product_attributes "
                    "WHERE productclass_id=?",
                    (row["id"],),
                ).fetchall()
            ]

            for row_1 in c.execute(
                "SELECT * "
                "FROM products_productattribute "
                "WHERE id IN ({})".format(",".join("?" * len(attr_ids))),
                attr_ids,
            ):
                attr, _ = models.Attribute.objects.get_or_create(
                    name=row_1[1], slug=row_1[2], value_required=not bool(row_1[3])
                )
                models.AttributeProduct.objects.get_or_create(
                    attribute=attr, product_type=product_type
                )
                attribute_map[int(row_1[0])] = attr

            # Create all product variant specific attributes for that ProductType
            attr_ids = [
                x[0]
                for x in c.execute(
                    "SELECT productattribute_id "
                    "FROM products_productclass_variant_attributes "
                    "WHERE productclass_id=?",
                    (row["id"],),
                ).fetchall()
            ]

            for row_1 in c.execute(
                "SELECT * "
                "FROM products_productattribute "
                "WHERE id IN ({})".format(",".join("?" * len(attr_ids))),
                attr_ids,
            ):
                attr, _ = models.Attribute.objects.get_or_create(
                    name=row_1[1],
                    slug=row_1[2],
                    value_required=not bool(row_1[3]),
                    is_variant_only=True,
                )
                models.AttributeVariant.objects.get_or_create(
                    attribute=attr, product_type=product_type
                )
                attribute_map[int(row_1[0])] = attr

        # -----------------------------------------------------------------------
        # A T T R I B U T E   V A L U E S
        # -----------------------------------------------------------------------

        # Then create all attribute values
        for row in dictfetchall(
            c.execute("SELECT * FROM products_attributechoicevalue")
        ):
            # attr_value, created = models.AttributeValue.objects.get_or_create(
            #     name=row["name"],
            #     slug=row["slug"],
            #     attribute=attribute_map[row["attribute_id"]],
            #     # sort_order=row["position"],
            # )
            # if created:
            #     attr_value.sort_order = row["position"]
            #     attr_value.save()
            attr_value = get_or_create_attribute_value(
                name=row["name"],
                slug=row["slug"],
                attribute=attribute_map[row["attribute_id"]],
                sort_order=row["position"],
            )

            attribute_value_map[int(row["id"])] = attr_value

        # -----------------------------------------------------------------------
        # C A T E G O R I E S
        # -----------------------------------------------------------------------

        # Then create all categories
        with connection.cursor() as dj_c:
            for row in dictfetchall(c.execute("select * from products_category")):
                sql = (
                    "INSERT INTO product_category (id, name, slug, description, lft, rght, tree_id, level, parent_id, background_image, seo_description, seo_title, background_image_alt, description_json, metadata, private_metadata) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '', '', '', '', '{}', '{}', '{}') "
                    "ON CONFLICT DO NOTHING"
                )
                row.pop("hidden")
                dj_c.execute(sql, list(row.values()))

        # -----------------------------------------------------------------------
        # P R O D U C T S
        # -----------------------------------------------------------------------

        # Then import all products
        for row in dictfetchall(c.execute("SELECT * FROM products_product")):
            category = c.execute(
                "SELECT category_id "
                "FROM products_product_categories "
                "WHERE product_id=?",
                [row["id"]],
            ).fetchone()
            
            product, _ = models.Product.objects.get_or_create(
                product_type=product_type_map[row["product_class_id"]],
                name=row["name"],
		        slug=slugify(row["name"]),
                category=models.Category.objects.get(id=category[0]),
                price_amount=row["price"],
                currency=row["price_currency"],
                is_published=True,
            )

            product_map[int(row["id"])] = product

            attributes = json.loads(row["attributes"])
            for attr_id, attr_value_id in attributes.items():
                # print(attribute_map[int(attr_id)], attribute_value_map[int(attr_value_id)])
                attr = attribute_map[int(attr_id)]

                attr_product = models.AttributeProduct.objects.get(
                    attribute=attr,
                    product_type=product_type_map[row["product_class_id"]],
                )
                attr_product.assigned_products.add(product)

                (
                    assignment,
                    created,
                ) = models.AssignedProductAttribute.objects.get_or_create(
                    product=product, assignment=attr_product
                )
                attr_value = attribute_value_map[attr_value_id]

                # if created:
                assignment.values.set([attr_value])

                # The above logic is taken from
                # # The logic is taken from:
                # saleor/product/utils/attributes.py::associate_attribute_values_to_instance
                # and might be simply replaced with:
                # associate_attribute_values_to_instance(
                #     product, attr, attr_value
                # )

        # -----------------------------------------------------------------------
        # S H I P P I N G  Z O N E S
        # -----------------------------------------------------------------------

        at_zone, _ = sm.ShippingZone.objects.get_or_create(
            name="Austria",
            countries=["AT"],
            default=True
        )

        countries = list(COUNTRIES.keys())
        countries.remove("AT")
        world_zone, _ = sm.ShippingZone.objects.get_or_create(
            name="World",
            countries=countries,
            default=True
        )

        # -----------------------------------------------------------------------
        # W A R E H O U S E
        # -----------------------------------------------------------------------

        address, _ = am.Address.objects.get_or_create(
            first_name="Gernot",
            last_name="Cseh",
            company_name="Howling Wolf Pedals",
            street_address_1="Körösistraße 56",
            city="Graz",
            postal_code="8010",
            country="AT",
            phone="+436801253030",
        )
        
        if address:
            warehouse, _ = wm.Warehouse.objects.get_or_create(
                name="Headquater Graz",
                slug = slugify("Headquater Graz"),
                #company_name = 
                #shipping_zones = 
                address = address,
                email="gernot.cseh@gmail.com",
            )
            warehouse.shipping_zones.add(at_zone, world_zone)

        # -----------------------------------------------------------------------
        # P R O D U C T   V A R I A N T S
        # -----------------------------------------------------------------------

        for row in dictfetchall(c.execute("SELECT * FROM products_productvariant")):
            # product = models.Product.objects.get(id=row["product_id"])
            product = product_map[int(row["product_id"])]

            attributes = json.loads(row["attributes"])

            dca75_result = c.execute(
                "SELECT data FROM products_dca75result WHERE variant_id=?", [row["id"]]
            ).fetchone()

            product_variant, _ = models.ProductVariant.objects.get_or_create(
                sku=row["sku"],
                price_override_amount=row["price_override"],
                currency=row["price_override_currency"],
                product=product,
                metadata=(
                    {"dca75_result": json.loads(dca75_result[0])}
                    if dca75_result
                    else {}
                ),
            )

            stock_quantity = c.execute(
                "SELECT quantity FROM products_stock WHERE variant_id=?", [row["id"]]
            ).fetchone()

            stock, _ = wm.Stock.objects.get_or_create(
                warehouse=warehouse,
                product_variant=product_variant,
                quantity=int(stock_quantity[0])
            )
            
            # Save DCA75Pro result in the product variant metadata

            for attr_id, attr_value in attributes.items():
                attr = attribute_map[int(attr_id)]
                attr_variant = models.AttributeVariant.objects.get(
                    attribute=attr, product_type=product.product_type,
                )
                attr_variant.assigned_variants.add(product_variant)

                (
                    assignment,
                    created,
                ) = models.AssignedVariantAttribute.objects.get_or_create(
                    variant=product_variant, assignment=attr_variant
                )

                attr_value = get_or_create_attribute_value(
                    attr_value, attribute_map[int(attr_id)]
                )

                assignment.values.set([attr_value])

                # The above logic is taken from
                # # The logic is taken from:
                # saleor/product/utils/attributes.py::associate_attribute_values_to_instance
                # and might be simply replaced with:
                # associate_attribute_values_to_instance(
                #     product_variant, attr, attr_value
                # )

            # The storefront needs this exact name to function
            # saleor/product/utils/attributes.py::generate_name_for_variant
            product_variant.name = generate_name_for_variant(product_variant)
            product_variant.save(update_fields=["name"])


# Get Graphene global id
# See: https://github.com/graphql-python/graphene-django/issues/578#issuecomment-459723462
# from graphql_relay import to_global_id
# from saleor.product import models
# to_global_id(models.Product._meta.object_name, 1)

# GraphQL query
# query {
#   product(id: "UHJvZHVjdDoy") {
#     name
#     variants {
#       name
#       meta {
#         namespace
#         clients {
#           name
#           metadata {
#             key
#             value
#           }
#         }
#       }
#     }
#   }
# }
