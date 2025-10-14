# Django imports
from django.shortcuts import render, redirect, get_object_or_404  # Rendering templates, redirects, and fetching objects
from django.utils.decorators import method_decorator  # For decorating class-based views
from django.views.decorators.csrf import csrf_exempt  # Exempting views from CSRF verification
from django.core.cache import cache  # Django caching framework
from django.conf import settings  # Accessing Django settings
from django.core.mail import send_mail, EmailMessage  # Sending emails
from django.template.loader import render_to_string  # Rendering templates to string
from django.contrib.sites.shortcuts import get_current_site  # Getting current site info
from django.contrib.auth import get_user_model  # Getting the user model

# Third-party imports
from rest_framework.decorators import api_view, permission_classes, action  # DRF view decorators
from rest_framework.permissions import IsAuthenticated, AllowAny  # DRF permission classes
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer  # JWT token serializer
from rest_framework_simplejwt.views import TokenObtainPairView  # JWT token view
from rest_framework_simplejwt.tokens import RefreshToken  # JWT refresh token
from rest_framework_simplejwt.authentication import JWTAuthentication  # JWT authentication backend
from rest_framework import status, generics, viewsets, permissions  # DRF status codes, generic views, viewsets, permissions
from rest_framework.response import Response  # DRF response object
from rest_framework.views import APIView  # DRF APIView base class
from rest_framework.exceptions import PermissionDenied  # DRF exception for permission denied

from social_django.utils import load_strategy  # Social auth strategy loader

# Standard library imports
import json  # JSON encoding and decoding
import random  # Random number generation

#swagger authentication

from rest_framework.permissions import BasePermission
from rest_framework import permissions

class IsAuthenticatedForSwagger(BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated
    

# Create your views here.
class MyTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['email'] = user.email
        token['id'] = user.id  # This should match 'id'
        token['first_name'] = user.first_name
        return token

    
class MyTokenObtainPairView(TokenObtainPairView):
    serializer_class = MyTokenObtainPairSerializer




# users/views.py
import random
from django.core.cache import cache
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.contrib.sites.shortcuts import get_current_site
from django.shortcuts import get_object_or_404

from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework_simplejwt.tokens import RefreshToken, TokenError

from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi

from .models import CustomUser as User
from .serializers import (
    UserSerializer,
    UserRegistrationSerializer,
    ChangePasswordSerializer,
    UserProfileUpdateSerializer
)
from .permissions import IsAdminUser


import logging
logger = logging.getLogger(__name__)


# ==================== OTP GENERATION ====================
@swagger_auto_schema(
    method='post',
    operation_summary="Generate OTP for Login",
    operation_description="Generates and sends a 6-digit OTP to the user's email or phone number for authentication.",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=['identifier'],
        properties={
            'identifier': openapi.Schema(
                type=openapi.TYPE_STRING,
                description='Email address or phone number'
            ),
        }
    ),
    responses={
        200: openapi.Response(
            description="OTP sent successfully",
            examples={
                "application/json": {
                    "message": "OTP sent successfully.",
                    "identifier": "user@example.com"
                }
            }
        ),
        400: "Invalid request - identifier missing",
        404: "User not found or inactive"
    },
    tags=['Authentication']
)
@api_view(['POST'])
@permission_classes([AllowAny])
def generate_otp(request):
    """
    Generate and send OTP for user login.
    Supports both email and phone number.
    """
    identifier = request.data.get('identifier')
    
    if not identifier:
        return Response(
            {'error': 'Email or phone number is required.'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        # Find user by email or phone
        if '@' in identifier:
            user = User.objects.get(email=identifier)
        else:
            user = User.objects.get(phone=identifier)
        
        if not user.is_active:
            return Response(
                {
                    'error': 'This user is inactive. Please contact administrator.',
                    'is_active': False
                },
                status=status.HTTP_403_FORBIDDEN
            )
    
    except User.DoesNotExist:
        return Response(
            {'error': 'User does not exist.'},
            status=status.HTTP_404_NOT_FOUND
        )
    
    # Generate 6-digit OTP
    otp = random.randint(100000, 999999)
    
    # Save OTP in cache for 10 minutes
    cache.set(f'otp_{identifier}', otp, timeout=600)
    
    # Send OTP via Email
    if user.email:
        try:
            current_site = get_current_site(request)
            mail_subject = 'OTP for Account Login - Phone Financing Platform'
            message = render_to_string('emails/otp_login.html', {
                'user': user,
                'otp': otp,
                'domain': current_site.domain,
                'validity': '10 minutes'
            })
            
            email = EmailMessage(mail_subject, message, to=[user.email])
            email.content_subtype = "html"
            email.send(fail_silently=False)
            logger.info(f"OTP email sent to {user.email}")
        except Exception as e:
            logger.error(f"Failed to send OTP email: {str(e)}")
    
    # Send OTP via SMS (if phone exists)
    if user.phone:
        try:
            # TODO: Integrate LabsMobile SMS service here
            # For now, just log it
            logger.info(f"OTP SMS would be sent to {user.phone}: {otp}")
            # sms_service = SMSService()
            # sms_service.send_sms(user.phone, f"Your login OTP: {otp}")
        except Exception as e:
            logger.error(f"Failed to send OTP SMS: {str(e)}")
    
    return Response(
        {
            'message': 'OTP sent successfully.',
            'identifier': identifier
        },
        status=status.HTTP_200_OK
    )


# ==================== OTP VERIFICATION & LOGIN ====================
@swagger_auto_schema(
    method='post',
    operation_summary="Verify OTP and Login",
    operation_description="Verifies the OTP and issues JWT access and refresh tokens.",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=['identifier', 'otp'],
        properties={
            'identifier': openapi.Schema(
                type=openapi.TYPE_STRING,
                description='Email or phone number'
            ),
            'otp': openapi.Schema(
                type=openapi.TYPE_STRING,
                description='6-digit OTP code'
            ),
        }
    ),
    responses={
        200: openapi.Response(
            description="Login successful",
            examples={
                "application/json": {
                    "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc...",
                    "access": "eyJ0eXAiOiJKV1QiLCJhbGc...",
                    "message": "Login successful.",
                    "user": {
                        "id": "uuid",
                        "email": "user@example.com",
                        "role": "salesperson"
                    },
                    "is_admin": False
                }
            }
        ),
        400: "Invalid or expired OTP",
        404: "User not found"
    },
    tags=['Authentication']
)
@api_view(['POST'])
@permission_classes([AllowAny])
def verify_otp_and_login(request):
    """
    Verify OTP and issue JWT tokens for authentication.
    """
    identifier = request.data.get('identifier')
    otp = request.data.get('otp')
    
    if not identifier or not otp:
        return Response(
            {'error': 'Identifier and OTP are required.'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Retrieve OTP from cache
    stored_otp = cache.get(f'otp_{identifier}')
    if stored_otp is None or str(stored_otp) != str(otp):
        return Response(
            {'error': 'Invalid or expired OTP.'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Find user
    try:
        if '@' in identifier:
            user = User.objects.get(email=identifier)
        else:
            user = User.objects.get(phone=identifier)
    except User.DoesNotExist:
        return Response(
            {'error': 'User does not exist.'},
            status=status.HTTP_404_NOT_FOUND
        )
    
    # Generate JWT tokens
    refresh = RefreshToken.for_user(user)
    access = refresh.access_token
    
    # Remove OTP from cache
    cache.delete(f'otp_{identifier}')
    
    # Serialize user data
    user_data = UserSerializer(user).data
    
    return Response(
        {
            'refresh': str(refresh),
            'access': str(access),
            'message': 'Login successful.',
            'user': user_data,
            'is_admin': user.is_superuser,
            'role': user.role
        },
        status=status.HTTP_200_OK
    )


# ==================== USER REGISTRATION (ADMIN ONLY) ====================
@swagger_auto_schema(
    method='post',
    operation_summary="Register New User (Admin Only)",
    operation_description="Admin creates a new user account. OTP will be sent for verification.",
    request_body=UserRegistrationSerializer,
    responses={
        200: openapi.Response(
            description="Registration initiated successfully",
            examples={
                "application/json": {
                    "message": "Registration initiated successfully. OTP sent for verification.",
                    "identifier": "newuser@example.com"
                }
            }
        ),
        400: "Invalid data or user already exists",
        403: "Admin access required"
    },
    tags=['User Management']
)
@api_view(['POST'])
@permission_classes([IsAdminUser])
def admin_create_user(request):
    """
    Admin-only endpoint to create new users.
    Sends OTP for email/phone verification.
    """
    email = request.data.get('email')
    phone = request.data.get('phone')
    
    # Validate required fields
    if not email and not phone:
        return Response(
            {"error": "Email or phone number is required."},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Check if user already exists
    if email and User.objects.filter(email=email).exists():
        return Response(
            {"error": "A user with this email already exists."},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    if phone and User.objects.filter(phone=phone).exists():
        return Response(
            {"error": "A user with this phone number already exists."},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Validate data
    serializer = UserRegistrationSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    # Store registration data in cache
    identifier = email if email else phone
    cache.set(f'registration_data_{identifier}', request.data.copy(), timeout=600)
    
    # Generate and send OTP
    success, message = generate_and_send_otp(identifier, is_registration=True)
    
    if success:
        return Response(
            {
                "message": "Registration initiated successfully. OTP sent for verification.",
                "detail": message,
                "identifier": identifier
            },
            status=status.HTTP_200_OK
        )
    else:
        return Response(
            {"error": message},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# ==================== VERIFY REGISTRATION OTP ====================
@swagger_auto_schema(
    method='post',
    operation_summary="Verify Registration OTP",
    operation_description="Verifies OTP and completes user registration.",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=['identifier', 'otp'],
        properties={
            'identifier': openapi.Schema(type=openapi.TYPE_STRING),
            'otp': openapi.Schema(type=openapi.TYPE_STRING),
        }
    ),
    responses={
        201: openapi.Response(
            description="Registration successful",
            examples={
                "application/json": {
                    "message": "User created successfully.",
                    "user": {
                        "id": "uuid",
                        "email": "user@example.com",
                        "role": "salesperson"
                    }
                }
            }
        ),
        400: "Invalid or expired OTP"
    },
    tags=['User Management']
)
@api_view(['POST'])
@permission_classes([AllowAny])
def verify_registration_otp(request):
    """
    Verify OTP and complete user registration.
    """
    identifier = request.data.get('identifier')
    otp = request.data.get('otp')
    
    if not identifier or not otp:
        return Response(
            {'error': 'Identifier and OTP are required.'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Retrieve OTP from cache
    stored_otp = cache.get(f'otp_{identifier}')
    if stored_otp is None or str(stored_otp) != str(otp):
        return Response(
            {'error': 'Invalid or expired OTP.'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Retrieve registration data
    registration_data = cache.get(f'registration_data_{identifier}')
    if not registration_data:
        return Response(
            {'error': 'Registration session expired. Please start again.'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Create user
    serializer = UserRegistrationSerializer(data=registration_data)
    if serializer.is_valid():
        user = serializer.save()
        user.is_verified = True
        user.save()
        
        # Clean up cache
        cache.delete(f'otp_{identifier}')
        cache.delete(f'registration_data_{identifier}')
        
        return Response(
            {
                'message': 'User created successfully.',
                'user': UserSerializer(user).data
            },
            status=status.HTTP_201_CREATED
        )
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ==================== RESEND OTP ====================
@swagger_auto_schema(
    method='post',
    operation_summary="Resend OTP",
    operation_description="Resends OTP for registration or login.",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=['identifier'],
        properties={
            'identifier': openapi.Schema(type=openapi.TYPE_STRING),
            'type': openapi.Schema(
                type=openapi.TYPE_STRING,
                enum=['login', 'registration'],
                default='login'
            ),
        }
    ),
    responses={
        200: "OTP resent successfully",
        400: "Invalid request"
    },
    tags=['Authentication']
)
@api_view(['POST'])
@permission_classes([AllowAny])
def resend_otp(request):
    """
    Resend OTP for login or registration.
    """
    identifier = request.data.get('identifier')
    otp_type = request.data.get('type', 'login')
    
    if not identifier:
        return Response(
            {'error': 'Email or phone number is required.'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    if otp_type == 'registration':
        # Check if registration data exists
        if not cache.get(f'registration_data_{identifier}'):
            return Response(
                {'error': 'No pending registration found.'},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    # Generate and send new OTP
    success, message = generate_and_send_otp(
        identifier, 
        is_registration=(otp_type == 'registration')
    )
    
    if success:
        return Response(
            {"message": "OTP resent successfully.", "detail": message},
            status=status.HTTP_200_OK
        )
    else:
        return Response(
            {"error": message},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# ==================== LOGOUT ====================
@swagger_auto_schema(
    method='post',
    operation_summary="Logout User",
    operation_description="Blacklists the provided JWT tokens and logs out the user.",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=['refresh', 'access'],
        properties={
            'refresh': openapi.Schema(type=openapi.TYPE_STRING),
            'access': openapi.Schema(type=openapi.TYPE_STRING),
        }
    ),
    responses={
        200: "Logout successful",
        400: "Invalid tokens"
    },
    tags=['Authentication']
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout(request):
    """
    Logout user by blacklisting tokens.
    """
    try:
        refresh_token = request.data.get('refresh')
        access_token = request.data.get('access')
        
        if not refresh_token or not access_token:
            return Response(
                {"error": "Both refresh and access tokens are required."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Blacklist refresh token
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except TokenError as e:
            return Response(
                {"error": f"Invalid refresh token: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Blacklist access token in cache
        cache.set(
            f'blacklisted_access_{access_token}',
            'blacklisted',
            timeout=24*60*60  # 24 hours
        )
        
        return Response(
            {"message": "Logout successful. Tokens have been invalidated."},
            status=status.HTTP_200_OK
        )
    
    except Exception as e:
        return Response(
            {"error": f"Logout failed: {str(e)}"},
            status=status.HTTP_400_BAD_REQUEST
        )


# ==================== USER PROFILE ====================
class UserProfileView(APIView):
    """
    Get and update user profile.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    
    @swagger_auto_schema(
        operation_summary="Get User Profile",
        operation_description="Retrieves the authenticated user's profile details.",
        responses={
            200: UserSerializer,
            401: "Authentication required"
        },
        tags=['User Profile']
    )
    def get(self, request):
        """Get current user profile"""
        serializer = UserSerializer(request.user)
        return Response(serializer.data)
    
    @swagger_auto_schema(
        operation_summary="Update User Profile",
        operation_description="Updates the authenticated user's profile. Supports partial updates.",
        request_body=UserProfileUpdateSerializer,
        responses={
            200: UserSerializer,
            400: "Invalid input data"
        },
        tags=['User Profile']
    )
    def patch(self, request):
        """Update user profile"""
        serializer = UserProfileUpdateSerializer(
            request.user,
            data=request.data,
            partial=True
        )
        if serializer.is_valid():
            serializer.save()
            return Response(
                UserSerializer(request.user).data,
                status=status.HTTP_200_OK
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ==================== CHANGE PASSWORD ====================
@swagger_auto_schema(
    method='post',
    operation_summary="Change Password",
    operation_description="Allows authenticated user to change their password.",
    request_body=ChangePasswordSerializer,
    responses={
        200: "Password changed successfully",
        400: "Invalid old password or validation error"
    },
    tags=['User Profile']
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password(request):
    """
    Change user password.
    """
    serializer = ChangePasswordSerializer(
        data=request.data,
        context={'request': request}
    )
    
    if serializer.is_valid():
        # Set new password
        request.user.set_password(serializer.validated_data['new_password'])
        request.user.save()
        
        return Response(
            {"message": "Password changed successfully."},
            status=status.HTTP_200_OK
        )
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ==================== ADMIN USER MANAGEMENT ====================
class ListAllUsers(ListAPIView):
    """
    Admin can view list of all registered users.
    """
    permission_classes = [IsAdminUser]
    queryset = User.objects.all()
    serializer_class = UserSerializer
    
    @swagger_auto_schema(
        operation_summary="List All Users (Admin)",
        operation_description="Retrieves a list of all users. Admin only.",
        responses={200: UserSerializer(many=True)},
        tags=['User Management']
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


@swagger_auto_schema(
    method='get',
    operation_summary="Get User by ID (Admin)",
    operation_description="Retrieves details of a specific user by ID. Admin only.",
    responses={
        200: UserSerializer,
        404: "User not found"
    },
    tags=['User Management']
)
@api_view(['GET'])
@permission_classes([IsAdminUser])
def get_user_by_id(request, pk):
    """
    Admin can get any user's details by ID.
    """
    user = get_object_or_404(User, id=pk)
    serializer = UserSerializer(user)
    return Response(serializer.data, status=status.HTTP_200_OK)


class ToggleUserActiveStatus(APIView):
    """
    Admin can block or unblock a user.
    """
    permission_classes = [IsAdminUser]
    
    @swagger_auto_schema(
        operation_summary="Toggle User Active Status (Admin)",
        operation_description="Block or unblock a user by toggling is_active status.",
        responses={
            200: openapi.Response(
                description="Status toggled successfully",
                examples={
                    "application/json": {
                        "message": "User blocked successfully.",
                        "user_id": "uuid",
                        "is_active": False
                    }
                }
            ),
            404: "User not found"
        },
        tags=['User Management']
    )
    def post(self, request, user_id):
        user = get_object_or_404(User, id=user_id)
        user.is_active = not user.is_active
        user.save()
        
        return Response(
            {
                "message": f"User {'unblocked' if user.is_active else 'blocked'} successfully.",
                "user_id": str(user.id),
                "is_active": user.is_active
            },
            status=status.HTTP_200_OK
        )


class DeleteUserByAdmin(APIView):
    """
    Admin can delete any user account.
    """
    permission_classes = [IsAdminUser]
    
    @swagger_auto_schema(
        operation_summary="Delete User (Admin)",
        operation_description="Permanently deletes a user account. Admin only.",
        responses={
            204: "User deleted successfully",
            404: "User not found"
        },
        tags=['User Management']
    )
    def delete(self, request, user_id):
        user = get_object_or_404(User, id=user_id)
        user.delete()
        return Response(
            {"message": "User deleted successfully."},
            status=status.HTTP_204_NO_CONTENT
        )


class DeleteOwnAccount(APIView):
    """
    Authenticated user can delete their own account.
    """
    permission_classes = [IsAuthenticated]
    
    @swagger_auto_schema(
        operation_summary="Delete Own Account",
        operation_description="Allows authenticated user to delete their own account.",
        responses={
            204: "Account deleted successfully",
            401: "Authentication required"
        },
        tags=['User Profile']
    )
    def delete(self, request):
        user = request.user
        user.delete()
        return Response(
            {"message": "Your account has been deleted."},
            status=status.HTTP_204_NO_CONTENT
        )


# ==================== HELPER FUNCTIONS ====================
def generate_and_send_otp(identifier, is_registration=False):
    otp = random.randint(100000, 999999)
    cache.set(f'otp_{identifier}', otp, timeout=600)
    
    if '@' in identifier:
        try:
            subject = 'OTP for Registration' if is_registration else 'OTP for Login'
            template = 'emails/otp_registration.html' if is_registration else 'emails/otp_login.html'
            
            message = render_to_string(template, {
                'otp': otp,
                'domain': 'byteboot.com',  # Update with your domain
                'validity': '10 minutes'
            })
            
            email_message = EmailMessage(subject, message, to=[identifier])
            email_message.content_subtype = "html"
            email_message.send(fail_silently=False)
            
            return True, "OTP sent to your email successfully."
        except Exception as e:
            logger.error(f"Email OTP send failed: {str(e)}")
            return False, f"Failed to send OTP via email: {str(e)}"





