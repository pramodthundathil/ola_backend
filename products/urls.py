from django.urls import path
from .import views

urlpatterns = [  

    # Create Category(Admin or Global Manager only)
    path('categories/', views.ProductCategoryCreateView.as_view(), name='category-create'),    
    path('categories/<int:pk>/', views.ProductCategoryDetailView.as_view(), name='category-detail'),  
    path('brand/', views.ProductBrandCreateView.as_view(), name='product-category-brand'),
    path('brand/<int:pk>/', views.ProductBrandDetailView.as_view(), name='brand-detail'),
    path('model/', views.ProductModelListCreateView.as_view(), name='product-model'),
    path('model/<int:pk>/', views.ProductModelDetailView.as_view(), name='model-detail'),
]
