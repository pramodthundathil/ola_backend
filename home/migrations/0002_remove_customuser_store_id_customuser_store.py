from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0001_initial'),  # Adjust to your previous migration
    ]

    operations = [
        # FIRST: Remove the index on store_id
        migrations.RemoveIndex(
            model_name='customuser',
            name='custom_user_store_i_cdf226_idx',  # Use the actual index name
        ),
        
        # THEN: Remove the store_id field
        migrations.RemoveField(
            model_name='customuser',
            name='store_id',
        ),
        
        # FINALLY: Add the store ForeignKey
        migrations.AddField(
            model_name='customuser',
            name='store',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='employees',
                to='store.store'
            ),
        ),
    ]