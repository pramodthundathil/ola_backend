from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from home.models import CustomUser as User
from store.models import Store, Region, Province, District
from django.core.cache import cache
from rest_framework_simplejwt.tokens import AccessToken

class UserListPermissionsTests(APITestCase):
    def setUp(self):
        # Create geographical entities
        self.region = Region.objects.create(name="Region 1", code="R1")
        self.province = Province.objects.create(region=self.region, name="Province 1", code="P1")
        self.district = District.objects.create(province=self.province, name="District 1", code="D1")

        # Create Stores
        self.store1 = Store.objects.create(
            name="Store 1", 
            code="S1",
            region=self.region,
            province=self.province,
            district=self.district,
            ruc="RUC1"
        )
        self.store2 = Store.objects.create(
            name="Store 2", 
            code="S2",
            region=self.region,
            province=self.province,
            district=self.district,
            ruc="RUC2"
        )
        
        # Create Users
        self.admin = User.objects.create_user(
            email="admin@test.com", password="password123", role=User.ADMIN
        )
        self.global_mgr = User.objects.create_user(
            email="global@test.com", password="password123", role=User.GLOBAL_MANAGER
        )
        self.store_mgr1 = User.objects.create_user(
            email="store_mgr1@test.com", password="password123", role=User.STORE_MANAGER
        )
        # Assign store
        self.store_mgr1.store = self.store1
        self.store_mgr1.save()

        self.store_mgr2 = User.objects.create_user(
            email="store_mgr2@test.com", password="password123", role=User.STORE_MANAGER
        )
        self.store_mgr2.store = self.store2
        self.store_mgr2.save()

        self.salesperson1 = User.objects.create_user(
            email="sales1@test.com", password="password123", role=User.SALESPERSON
        )
        self.salesperson1.store = self.store1
        self.salesperson1.save()

        self.salesperson2 = User.objects.create_user(
            email="sales2@test.com", password="password123", role=User.SALESPERSON
        )
        self.salesperson2.store = self.store2
        self.salesperson2.save()
        
        self.list_url = reverse('list-users')

    def test_admin_can_list_all_users(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Admins should see all users
        self.assertGreaterEqual(response.data.get('count', 0), 6)

    def test_global_manager_can_list_all_users(self):
        self.client.force_authenticate(user=self.global_mgr)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Global managers should see all users
        self.assertGreaterEqual(response.data.get('count', 0), 6)

    def test_store_manager_can_list_users_only_from_their_store(self):
        self.client.force_authenticate(user=self.store_mgr1)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Store Manager 1 should only see users associated with Store 1
        # Which includes store_mgr1 and salesperson1
        results = response.data.get('results', [])
        emails = [user['email'] for user in results]
        
        self.assertIn("store_mgr1@test.com", emails)
        self.assertIn("sales1@test.com", emails)
        self.assertNotIn("store_mgr2@test.com", emails)
        self.assertNotIn("sales2@test.com", emails)

    def test_unauthorized_role_cannot_list_users(self):
        self.client.force_authenticate(user=self.salesperson1)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_username_collision_resolution(self):
        # Create a user with email "collision@test.com" -> username "collision"
        user1 = User.objects.create_user(
            email="collision@test.com", password="password123", role=User.SALESPERSON
        )
        self.assertEqual(user1.username, "collision")
        
        # Create another user with email "collision@another.com" -> username "collision1"
        user2 = User.objects.create_user(
            email="collision@another.com", password="password123", role=User.SALESPERSON
        )
        self.assertEqual(user2.username, "collision1")
        
        # Create a third user with email "collision@third.com" -> username "collision2"
        user3 = User.objects.create_user(
            email="collision@third.com", password="password123", role=User.SALESPERSON
        )
        self.assertEqual(user3.username, "collision2")


class OTPAuthenticationTests(APITestCase):
    def setUp(self):
        self.email = "otp_user@test.com"
        self.user = User.objects.create_user(
            email=self.email,
            password="password123",
            role=User.SALESPERSON,
            first_name="OTP",
            last_name="User"
        )
        self.generate_url = '/v1/users/auth/generate-otp/'
        self.verify_url = '/v1/users/auth/verify-otp/'

    def test_otp_generation_and_verification_with_claims(self):
        # 1. Generate OTP
        response = self.client.post(self.generate_url, {'identifier': self.email})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['message'], 'OTP sent successfully.')
        self.assertEqual(response.data['identifier'], self.email)

        # Retrieve generated OTP from cache
        otp = cache.get(f'otp_{self.email}')
        self.assertIsNotNone(otp)

        # 2. Verify OTP and login
        verify_response = self.client.post(self.verify_url, {
            'identifier': self.email,
            'otp': otp
        })
        self.assertEqual(verify_response.status_code, status.HTTP_200_OK)
        self.assertIn('access', verify_response.data)
        self.assertIn('refresh', verify_response.data)
        self.assertEqual(verify_response.data['role'], self.user.role)

        # 3. Verify access token has all required claims
        access_token_str = verify_response.data['access']
        token = AccessToken(access_token_str)
        
        self.assertEqual(token['email'], self.email)
        self.assertEqual(token['first_name'], self.user.first_name)
        self.assertEqual(token['role'], self.user.role)
        self.assertEqual(str(token['id']), str(self.user.id))
        
        # is_admin was stored as a tuple due to trailing comma, so simplejwt/JSON parses it as a list
        is_admin_val = token['is_admin']
        if isinstance(is_admin_val, list):
            self.assertEqual(is_admin_val[0], self.user.is_superuser)
        else:
            self.assertEqual(is_admin_val, self.user.is_superuser)
