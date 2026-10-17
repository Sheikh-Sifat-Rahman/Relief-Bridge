from django.db import migrations


def opening_balances(apps, schema_editor):
    Stock = apps.get_model("inventory", "InventoryItem")
    Batch = apps.get_model("inventory", "InventoryBatch")
    alias = schema_editor.connection.alias
    for stock in Stock.objects.using(alias).filter(current_quantity__gt=0).iterator():
        Batch.objects.using(alias).create(
            inventory_item_id=stock.pk,
            source="OPENING",
            received_quantity=stock.current_quantity,
            remaining_quantity=stock.current_quantity,
            reserved_quantity=0,
        )


class Migration(migrations.Migration):
    dependencies = [("inventory", "0003_inventorybatch")]
    operations = [migrations.RunPython(opening_balances, migrations.RunPython.noop)]
