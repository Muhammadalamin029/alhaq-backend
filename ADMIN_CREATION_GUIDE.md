# 🔧 Admin User Creation Guide

This guide explains how to create admin users for the Alhaq platform.

## 🚀 Methods to Create Admin Users

### 1. **Interactive Script (Recommended for First Admin)**

Use the interactive script for secure admin creation:

```bash
cd /home/labtraca/Documents/alhaq/alhaq-backend
python create_admin.py
```

**Features:**
- ✅ Interactive prompts for all details
- ✅ Password validation and confirmation
- ✅ Email format validation
- ✅ Secure password input (hidden)
- ✅ Duplicate user checking

### 2. **Direct Script (Quick Setup)**

For quick setup with predefined credentials:

```bash
cd /home/labtraca/Documents/alhaq/alhaq-backend
python create_admin_direct.py
```

**⚠️ IMPORTANT:** Modify the credentials in `create_admin_direct.py` before running:

```python
# 🔧 MODIFY THESE CREDENTIALS
ADMIN_EMAIL = "admin@alhaq.com"
ADMIN_PASSWORD = "AdminPass123!"
ADMIN_BUSINESS_NAME = "Alhaq Administration"
ADMIN_DESCRIPTION = "Platform Administrator"
```

### 3. **API Endpoint (For Existing Admins)**

Once you have at least one admin, you can create additional admins via API:

```http
POST /admin/create-admin
Authorization: Bearer <admin_jwt_token>
Content-Type: application/json

{
  "email": "newadmin@alhaq.com",
  "password": "SecurePass123!",
  "business_name": "New Administrator",
  "description": "Additional System Administrator"
}
```

## 🔐 Password Requirements

All admin passwords must meet these requirements:
- ✅ At least 8 characters long
- ✅ Contains uppercase letter (A-Z)
- ✅ Contains lowercase letter (a-z)
- ✅ Contains number (0-9)
- ✅ Contains special character (!@#$%^&*)

## 📋 Admin User Structure

Admin users are created with:
- **Role**: `admin`
- **Profile Type**: `SellerProfile` (admins use seller profile structure)
- **KYC Status**: `approved` (automatically approved)
- **Permissions**: Full platform access

## 🎯 What Admins Can Do

Once created, admin users can:

### **Platform Management:**
- 👥 Manage all users (view, lock, unlock)
- 🏪 Approve/reject seller KYC applications
- 📦 Moderate all products (approve, reject, remove)
- 📋 Monitor all orders across the platform
- 📊 Access platform-wide analytics

### **Seller Functionality:**
- 📦 Access all products (platform-wide view)
- 📋 Monitor all orders (platform-wide view)
- 📈 View platform analytics
- ⚙️ Manage admin profile settings

### **Admin Operations:**
- 👨‍💼 Create additional admin users (via API)
- 🔧 Access admin dashboard
- 📊 View real-time platform statistics

## 🚨 Security Notes

1. **First Admin Creation**: Use the interactive script for the first admin to ensure security
2. **Password Security**: Always use strong, unique passwords
3. **Change Default Passwords**: If using the direct script, change the password after first login
4. **Limit Admin Users**: Only create admin users when necessary
5. **Audit Trail**: All admin creation activities are logged

## 🔍 Verification

After creating an admin user, verify it was created successfully:

1. **Check Database**: Look for the user in the `users` table with `role = 'admin'`
2. **Test Login**: Try logging in with the admin credentials
3. **Access Admin Dashboard**: Navigate to `/admin/dashboard` after login
4. **Check Logs**: Review the application logs for creation confirmation

## 🛠️ Troubleshooting

### **Common Issues:**

1. **"User already exists"**
   - Solution: Use a different email address

2. **"Password validation failed"**
   - Solution: Ensure password meets all requirements

3. **"Database connection error"**
   - Solution: Ensure database is running and accessible

4. **"Permission denied"**
   - Solution: Ensure you have proper file permissions

### **Getting Help:**

If you encounter issues:
1. Check the application logs in the console output
2. Verify database connectivity
3. Ensure all dependencies are installed
4. Check file permissions on scripts

## 📝 Example Usage

### Creating First Admin:
```bash
# Interactive method (recommended)
python create_admin.py

# Follow the prompts:
# Enter admin email: admin@alhaq.com
# Enter admin/business name: Alhaq Administration
# Enter description: Platform Administrator
# Enter admin password: [hidden input]
# Confirm admin password: [hidden input]
```

### Creating Additional Admins (via API):
```bash
# First, get admin JWT token by logging in
curl -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@alhaq.com", "password": "AdminPass123!"}'

# Use the token to create new admin
curl -X POST "http://localhost:8000/admin/create-admin" \
  -H "Authorization: Bearer <jwt_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin2@alhaq.com",
    "password": "SecurePass456!",
    "business_name": "Secondary Administrator",
    "description": "Additional Platform Administrator"
  }'
```

---

**🎉 You're all set!** Your admin user should now be created and ready to manage the Alhaq platform.
