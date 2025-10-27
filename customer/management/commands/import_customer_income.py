import pandas as pd
from django.core.management.base import BaseCommand
from customer.models import CustomerIncome  


class Command(BaseCommand):
    help = 'Import customer income data from Excel file'

    def handle(self, *args, **options):
        file_path = 'customer/data/CSS.xlsx' 
        try:
            df = pd.read_excel(file_path)

            
            df = df.rename(columns={
                'CEDULA': 'document_id',
                'PATRONO': 'employer',
                'SALARIO': 'monthly_income'
            })

            # Insert or update records
            for _, row in df.iterrows():
                CustomerIncome.objects.update_or_create(
                    document_id=row['document_id'],
                    defaults={
                        'employer': row['employer'],
                        'monthly_income': row['monthly_income']
                    }
                )
            self.stdout.write(self.style.SUCCESS('Customer income data imported successfully.'))

        except Exception as e:
            self.stderr.write(self.style.ERROR(f'Error importing data: {e}'))
