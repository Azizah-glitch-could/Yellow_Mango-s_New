from django.contrib.auth.models import User
from store.models import UserProfile, Order, OrderItem, Product


def save_user_session_backup(request, user):
    """
    Menyimpan data identitas user penting ke dalam signed cookie session.
    Ini memastikan sesi login pelanggan tetap bertahan di Vercel Serverless
    meskipun request berikutnya berpindah ke container serverless baru.
    """
    request.session['_user_backup_data'] = {
        'id': user.id,
        'username': user.username,
        'email': user.email or '',
        'first_name': user.first_name or '',
        'last_name': user.last_name or '',
        'password': user.password,
        'is_staff': user.is_staff,
        'is_superuser': user.is_superuser,
    }
    request.session.modified = True


def restore_order_from_backup(request, order_number):
    """
    Memulihkan Order ke SQLite container saat ini jika container belum memiliki datanya.
    """
    order_backup = request.session.get('last_order_backup')
    if not order_backup or not isinstance(order_backup, dict):
        return None
    if order_backup.get('order_number') != order_number:
        return None

    try:
        cust_user = None
        if order_backup.get('customer_id'):
            cust_user = User.objects.filter(pk=order_backup['customer_id']).first()

        order = Order.objects.create(
            order_number=order_backup['order_number'],
            customer=cust_user,
            customer_name=order_backup.get('customer_name', ''),
            customer_phone=order_backup.get('customer_phone', ''),
            notes=order_backup.get('notes', ''),
            total_amount=int(order_backup.get('total_amount', 0)),
            status=order_backup.get('status', 'PENDING'),
            payment_status=order_backup.get('payment_status', 'UNPAID'),
            payment_type=order_backup.get('payment_type', ''),
            midtrans_token=order_backup.get('midtrans_token', ''),
        )
        for itm in order_backup.get('items', []):
            prod = Product.objects.filter(id=itm.get('product_id')).first() if itm.get('product_id') else None
            OrderItem.objects.create(
                order=order,
                product=prod,
                product_name=itm.get('name', 'Menu'),
                price=int(itm.get('price', 0)),
                quantity=int(itm.get('quantity', 1)),
            )
        return order
    except Exception:
        return Order.objects.filter(order_number=order_number).first()


class ServerlessSyncMiddleware:
    """
    Middleware sinkronisasi state untuk arsitektur serverless Vercel:
    Secara otomatis meregenerasi record pengguna atau pesanan pada container ephemeral
    berdasarkan data terverifikasi dari Signed Session Cookie HMAC.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user_id = request.session.get('_auth_user_id')
        user_data = request.session.get('_user_backup_data')

        if user_id and user_data:
            try:
                uid = int(user_id)
                if not User.objects.filter(pk=uid).exists():
                    user = User(
                        id=uid,
                        username=user_data.get('username', f'user_{uid}'),
                        email=user_data.get('email', ''),
                        first_name=user_data.get('first_name', ''),
                        last_name=user_data.get('last_name', ''),
                        password=user_data.get('password', ''),
                        is_staff=user_data.get('is_staff', False),
                        is_superuser=user_data.get('is_superuser', False),
                        is_active=True,
                    )
                    user.save()
                    UserProfile.objects.get_or_create(user=user)
            except Exception:
                pass

        # Handle restore order jika ada request ke payment atau success
        order_backup = request.session.get('last_order_backup')
        if order_backup and isinstance(order_backup, dict):
            order_num = order_backup.get('order_number')
            if order_num and not Order.objects.filter(order_number=order_num).exists():
                restore_order_from_backup(request, order_num)

        response = self.get_response(request)
        return response
