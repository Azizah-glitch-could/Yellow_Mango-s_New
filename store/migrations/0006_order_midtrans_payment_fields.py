from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0005_alter_product_category_userprofile'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='payment_status',
            field=models.CharField(db_index=True, default='UNPAID', max_length=20),
        ),
        migrations.AddField(
            model_name='order',
            name='midtrans_token',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='order',
            name='midtrans_redirect_url',
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name='order',
            name='midtrans_transaction_id',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='order',
            name='payment_type',
            field=models.CharField(blank=True, max_length=40),
        ),
    ]
