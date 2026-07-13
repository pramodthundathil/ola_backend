from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from datetime import date

from analytics.models import DailyAnalytics, DashboardSummary
from analytics.services import AnalyticsService

User = get_user_model()


class AnalyticsAccessControlTests(APITestCase):
    """
    Unit tests for checking role-based permissions and endpoints
    """
    
    def setUp(self):
        # Create different users
        self.admin_user = User.objects.create_user(
            email='admin@example.com',
            password='password',
            role='admin',
            first_name='Admin',
            last_name='User'
        )
        self.global_manager = User.objects.create_user(
            email='global@example.com',
            password='password',
            role='global_manager',
            first_name='Global',
            last_name='Manager'
        )
        self.salesperson = User.objects.create_user(
            email='salesperson@example.com',
            password='password',
            role='salesperson',
            first_name='Sales',
            last_name='Executive'
        )
        
        # Setup mock DB data
        self.test_date = date.today()
        DailyAnalytics.objects.create(
            date=self.test_date,
            total_applications=10,
            approved_applications=7,
            rejected_applications=3
        )
        DashboardSummary.objects.create(
            date=self.test_date,
            total_applications=10,
            total_customers=5,
            active_loans=4
        )

    def test_admin_access_allowed(self):
        """Admin should be allowed access to KPIs"""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('analytics-kpis')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_global_manager_access_allowed(self):
        """Global Manager should be allowed access to KPIs"""
        self.client.force_authenticate(user=self.global_manager)
        url = reverse('analytics-kpis')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_salesperson_access_denied(self):
        """Salesperson should be denied access (403 Forbidden)"""
        self.client.force_authenticate(user=self.salesperson)
        url = reverse('analytics-kpis')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_access_denied(self):
        """Anonymous user should be denied access (401 Unauthorized)"""
        url = reverse('analytics-kpis')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class ReportsExportTests(APITestCase):
    """
    Unit tests verifying downloadable report formats
    """
    
    def setUp(self):
        self.admin_user = User.objects.create_user(
            email='admin_report@example.com',
            password='password',
            role='admin',
            first_name='Admin',
            last_name='Report'
        )
        self.client.force_authenticate(user=self.admin_user)
        
        # Setup mock DB data
        self.test_date = date.today()
        DashboardSummary.objects.create(
            date=self.test_date,
            total_applications=5,
            total_customers=2,
            active_loans=1
        )

    def test_export_csv_format(self):
        url = reverse('analytics-reports-export')
        response = self.client.get(url, {'format': 'csv', 'report_type': 'kpis'})
        print("RESPONSE STATUS:", response.status_code)
        print("RESPONSE CONTENT:", response.content)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertTrue('attachment' in response['Content-Disposition'])

    def test_export_excel_format(self):
        url = reverse('analytics-reports-export')
        response = self.client.get(url, {'format': 'excel', 'report_type': 'kpis'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    def test_export_pdf_format(self):
        url = reverse('analytics-reports-export')
        response = self.client.get(url, {'format': 'pdf', 'report_type': 'kpis'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response['Content-Type'], 'application/pdf')


from unittest.mock import patch
from customer.models import Customer

class SignalsSafetyTests(APITestCase):
    """
    Unit tests to verify that Celery/Redis connection failures inside signals
    are handled gracefully and do not crash the primary model save operations.
    """

    @patch('analytics.signals.update_customer_analytics_task.delay')
    def test_customer_creation_succeeds_when_celery_fails(self, mock_delay):
        # Configure the mock to raise a connection/broker error simulating Celery/Redis downtime
        mock_delay.side_effect = ConnectionError("Error 61 connecting to localhost:6379. Connection refused.")

        # Saving/creating a Customer should succeed despite Celery/Redis being down
        try:
            customer = Customer.objects.create(
                document_number="8-999-999",
                first_name="Safe",
                last_name="Test"
            )
        except Exception as e:
            self.fail(f"Customer creation failed due to Celery task exception propagation: {e}")

        self.assertIsNotNone(customer.id)
        mock_delay.assert_called_once()
