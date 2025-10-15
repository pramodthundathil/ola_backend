from django.urls import path
from .import views

urlpatterns = [  

    # Create Category(Admin or Global Manager only)
    path('categories/', views.ProductCategoryCreateView.as_view(), name='category-create'),
 
]
