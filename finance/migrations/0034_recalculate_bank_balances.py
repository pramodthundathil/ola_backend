from django.db import migrations
from django.db.models import Sum
from decimal import Decimal

def recalculate_existing_bank_balances(apps, schema_editor):
    BankAccount = apps.get_model('finance', 'BankAccount')
    LedgerEntry = apps.get_model('finance', 'LedgerEntry')
    
    for bank_acc in BankAccount.objects.all():
        if not bank_acc.accounting_code:
            bank_acc.current_balance = bank_acc.initial_balance
            bank_acc.save(update_fields=['current_balance'])
            continue
            
        debits = LedgerEntry.objects.filter(accounting_code=bank_acc.accounting_code, type='DEBIT').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        credits = LedgerEntry.objects.filter(accounting_code=bank_acc.accounting_code, type='CREDIT').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        category = 'ASSET'
        if bank_acc.accounting_code:
            category = bank_acc.accounting_code.category
            
        if category == 'LIABILITY':
            calculated_balance = bank_acc.initial_balance + credits - debits
        else:
            calculated_balance = bank_acc.initial_balance + debits - credits
            
        bank_acc.current_balance = calculated_balance
        bank_acc.save(update_fields=['current_balance'])

class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0033_merchantsettlement_bill'),
    ]

    operations = [
        migrations.RunPython(recalculate_existing_bank_balances, reverse_code=migrations.RunPython.noop),
    ]
