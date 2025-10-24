from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        
        ('customer', '0002_remove_paymentrecord_credit_application_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='CreditConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('apc_approval_threshold', models.IntegerField(default=500, help_text='Minimum APC/Experian score required for approval')),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'db_table': 'credit_config',
            },
        ),
    ]
