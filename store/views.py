import uuid
import urllib.parse
import urllib.request
import csv
import hashlib
import hmac
import json
import logging
from decimal import Decimal, InvalidOperation

import midtransclient
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.utils.text import slugify
from django.utils import timezone
from django.http import HttpResponse, JsonResponse, HttpResponseBadRequest, HttpResponseServerError
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q
from .models import (
    Product,
    Order,
    OrderItem,
    Page,
    Article,
    Announcement,
    MediaAsset,
    ContactMessage,
    SiteSetting,
    ActivityLog,
    UserProfile,
)


# ==========================================
# 1. VIEW HALAMAN PUBLIK UTAMA
# ==========================================

def index(request):
    """
    Landing page utama Yellow Mango's:
    - Menampilkan produk terlaris / rekomendasi dari database
    - Menampilkan ulasan & testimoni dari database (ContactMessage)
    - Menampilkan artikel / blog terbaru dari database (Article)
    - Menampilkan pengumuman & promo aktif dari database (Announcement)
    """
    # 1. Produk Terlaris (Best Seller) dari Database
    best_sellers = Product.objects.filter(is_available=True).filter(
        Q(badge_primary='BEST_SELLER') | Q(badge_secondary='BEST_SELLER')
    )[:6]

    # Fallback jika belum ada yang diset Best Seller
    if not best_sellers.exists():
        best_sellers = Product.objects.filter(is_available=True)[:6]

    # 2. Katalog Preview
    all_products = Product.objects.filter(is_available=True)[:8]

    # 3. Artikel & Blog Terbaru (yang diterbitkan via Admin Panel)
    latest_articles = Article.objects.filter(is_published=True).order_by('-created_at')[:3]

    # 4. Pengumuman / Promo Aktif
    announcements = Announcement.objects.filter(is_active=True).order_by('-created_at')[:3]

    # 5. Testimoni dari Pelanggan (ContactMessage)
    testimonials = ContactMessage.objects.filter(is_read=True).order_by('-created_at')[:6]
    if not testimonials.exists():
        testimonials = ContactMessage.objects.all().order_by('-created_at')[:4]

    # Kategori untuk tombol filter cepat di landing page
    categories = [cat[0] for cat in Product.CATEGORY_CHOICES]

    context = {
        'best_sellers': best_sellers,
        'all_products': all_products,
        'latest_articles': latest_articles,
        'announcements': announcements,
        'testimonials': testimonials,
        'categories': categories,
    }
    return render(request, 'index.html', context)


def menu_view(request):
    """
    Katalog Menu lengkap dengan fitur:
    - Kolom Pencarian (Search Bar) berdasarkan nama & deskripsi
    - Filter Kategori (Smoothies, Dessert, Coffee, dll.)
    - Filter Label/Badge (Best Seller, Promo, Baru)
    - Pengurutan (Harga terendah/tertinggi, terpopuler, terbaru)
    """
    q = request.GET.get('q', '').strip()
    category = request.GET.get('category', '').strip()
    badge = request.GET.get('badge', '').strip()
    sort = request.GET.get('sort', 'default')

    queryset = Product.objects.filter(is_available=True)

    # 1. Filter Pencarian
    if q:
        queryset = queryset.filter(Q(name__icontains=q) | Q(description__icontains=q))

    # 2. Filter Kategori
    if category and category != 'ALL':
        queryset = queryset.filter(category=category)

    # 3. Filter Badge / Label
    if badge and badge != 'ALL':
        queryset = queryset.filter(Q(badge_primary=badge) | Q(badge_secondary=badge))

    # 4. Pengurutan
    if sort == 'price_asc':
        queryset = queryset.order_by('price')
    elif sort == 'price_desc':
        queryset = queryset.order_by('-price')
    elif sort == 'newest':
        queryset = queryset.order_by('-created_at')
    elif sort == 'popular':
        queryset = queryset.filter(badge_primary='BEST_SELLER').union(queryset)
    else:
        queryset = queryset.order_by('-id')

    # Daftar kategori unik dari model pilihan
    category_list = [choice[0] for choice in Product.CATEGORY_CHOICES]

    context = {
        'products': queryset,
        'category_list': category_list,
        'selected_category': category,
        'selected_badge': badge,
        'selected_sort': sort,
        'search_query': q,
        'total_found': queryset.count(),
    }
    return render(request, 'store/menu.html', context)


def product_detail_view(request, pk):
    """
    Halaman Detail Produk:
    - Deskripsi lengkap
    - Pilihan variasi ukuran (Reguler / Large)
    - Pilihan level gula & level es
    - Input catatan khusus & jumlah pesanan
    - Tombol Tambah ke Keranjang & Beli Sekarang
    """
    product = get_object_or_404(Product, pk=pk, is_available=True)
    related_products = Product.objects.filter(category=product.category, is_available=True).exclude(pk=pk)[:4]

    context = {
        'product': product,
        'related_products': related_products,
    }
    return render(request, 'store/product_detail.html', context)


# ==========================================
# 2. SISTEM KERANJANG BELANJA (DJANGO SESSIONS)
# ==========================================

def add_to_cart(request, product_id):
    """
    Menambahkan item ke keranjang belanja pengguna menggunakan Django Session.
    Mendukung opsi ukuran, level gula, level es, catatan khusus, dan jumlah (qty).
    Mendukung request AJAX (JSON) dan formulir normal.
    """
    product = get_object_or_404(Product, id=product_id, is_available=True)

    if request.method == 'POST':
        try:
            quantity = int(request.POST.get('quantity', 1))
            if quantity < 1:
                quantity = 1
        except (ValueError, TypeError):
            quantity = 1

        size = request.POST.get('size', 'Reguler')
        sugar = request.POST.get('sugar', 'Normal')
        ice = request.POST.get('ice', 'Normal')
        notes = request.POST.get('notes', '').strip()
        direct_checkout = request.POST.get('direct_checkout') == 'true'
    else:
        quantity = 1
        size = 'Reguler'
        sugar = 'Normal'
        ice = 'Normal'
        notes = ''
        direct_checkout = False

    # Tambahan biaya jika memilih Large (+ Rp 4.000)
    extra_price = 4000 if size == 'Large' else 0
    unit_price = float(product.price) + extra_price

    # Buat item key unik berdasarkan variasi yang dipilih
    clean_notes = notes.replace(' ', '_')[:20]
    item_key = f"{product.id}_{size}_{sugar}_{ice}_{clean_notes}"

    cart = request.session.get('cart', {})
    if not isinstance(cart, dict):
        cart = {}

    image_url = product.image.url if product.image else (product.image_url or '/static/images/mangga.jpg')

    if item_key in cart:
        cart[item_key]['quantity'] += quantity
        cart[item_key]['subtotal'] = cart[item_key]['quantity'] * cart[item_key]['price']
    else:
        cart[item_key] = {
            'product_id': product.id,
            'name': product.name,
            'price': unit_price,
            'base_price': float(product.price),
            'quantity': quantity,
            'size': size,
            'sugar': sugar,
            'ice': ice,
            'notes': notes,
            'image': image_url,
            'subtotal': unit_price * quantity,
        }

    request.session['cart'] = cart
    request.session.modified = True

    # Hitung total sekarang
    total_qty = sum(item.get('quantity', 1) for item in cart.values())
    total_amount = sum(item.get('subtotal', 0) for item in cart.values())

    # Jika langsung klik 'Beli Sekarang'
    if direct_checkout:
        return redirect('checkout')

    # Jika request berupa AJAX
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('ajax') == '1':
        return JsonResponse({
            'success': True,
            'message': f"'{product.name}' berhasil dimasukkan ke keranjang!",
            'cart_count': total_qty,
            'cart_total': total_amount,
        })

    messages.success(request, f"'{product.name}' ({size}) berhasil dimasukkan ke keranjang belanja!")
    next_url = request.META.get('HTTP_REFERER') or '/cart/'
    return redirect(next_url)


def update_cart(request, item_key):
    """
    Mengubah kuantitas item dalam keranjang belanja (+, -, atau set manual).
    """
    cart = request.session.get('cart', {})
    if not isinstance(cart, dict):
        cart = {}

    if item_key in cart:
        action = request.POST.get('action') or request.GET.get('action')
        if action == 'increase':
            cart[item_key]['quantity'] += 1
        elif action == 'decrease':
            cart[item_key]['quantity'] -= 1
            if cart[item_key]['quantity'] <= 0:
                del cart[item_key]
        elif action == 'set':
            try:
                new_qty = int(request.POST.get('quantity', 1))
                if new_qty <= 0:
                    del cart[item_key]
                else:
                    cart[item_key]['quantity'] = new_qty
            except (ValueError, TypeError):
                pass

        if item_key in cart:
            cart[item_key]['subtotal'] = cart[item_key]['quantity'] * cart[item_key]['price']

        request.session['cart'] = cart
        request.session.modified = True

    total_qty = sum(item.get('quantity', 1) for item in cart.values())
    total_amount = sum(item.get('subtotal', 0) for item in cart.values())

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'cart_count': total_qty,
            'cart_total': total_amount,
            'item_subtotal': cart.get(item_key, {}).get('subtotal', 0),
            'item_quantity': cart.get(item_key, {}).get('quantity', 0),
        })

    return redirect('cart')


def remove_from_cart(request, item_key):
    """
    Menghapus satu item dari keranjang belanja.
    """
    cart = request.session.get('cart', {})
    if isinstance(cart, dict) and item_key in cart:
        item_name = cart[item_key].get('name', 'Menu')
        del cart[item_key]
        request.session['cart'] = cart
        request.session.modified = True
        messages.info(request, f"'{item_name}' telah dihapus dari keranjang belanja.")

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        total_qty = sum(item.get('quantity', 1) for item in cart.values())
        total_amount = sum(item.get('subtotal', 0) for item in cart.values())
        return JsonResponse({
            'success': True,
            'cart_count': total_qty,
            'cart_total': total_amount,
        })

    return redirect('cart')


def clear_cart(request):
    """
    Mengosongkan seluruh keranjang belanja.
    """
    request.session['cart'] = {}
    request.session.modified = True
    messages.info(request, "Keranjang belanja telah dikosongkan.")
    return redirect('cart')


def cart_view(request):
    """
    Halaman utama keranjang belanja (Shopping Cart View).
    """
    cart = request.session.get('cart', {})
    if not isinstance(cart, dict):
        cart = {}

    subtotal = sum(item.get('subtotal', 0) for item in cart.values())
    total_items = sum(item.get('quantity', 1) for item in cart.values())

    context = {
        'cart': cart,
        'subtotal': subtotal,
        'total_items': total_items,
        'grand_total': subtotal,
    }
    return render(request, 'store/cart.html', context)


# ==========================================
# 3. ALUR CHECKOUT & INTEGRASI WHATSAPP
# ==========================================

def _midtrans_snap_client():
    server_key = getattr(settings, 'MIDTRANS_SERVER_KEY', '')
    if not server_key:
        raise RuntimeError('MIDTRANS_SERVER_KEY belum diatur di file .env')
    return midtransclient.Snap(
        is_production=getattr(settings, 'MIDTRANS_IS_PRODUCTION', False),
        server_key=server_key,
    )


def _create_midtrans_transaction(order):
    """Buat token Snap di backend; Server Key tidak pernah dikirim ke browser."""
    items = []
    for item in order.items.all():
        items.append({
            'id': str(item.id),
            'price': int(item.price),
            'quantity': int(item.quantity),
            'name': item.product_name[:50],
        })

    # Midtrans mensyaratkan total item_details sama dengan gross_amount.
    if sum(row['price'] * row['quantity'] for row in items) != int(order.total_amount):
        raise ValueError('Total item pesanan tidak sama dengan total pembayaran.')

    customer_details = {
        'first_name': order.customer_name[:50],
        'phone': order.customer_phone[:20],
    }
    if order.customer and order.customer.email:
        customer_details['email'] = order.customer.email

    params = {
        'transaction_details': {
            'order_id': order.order_number,
            'gross_amount': int(order.total_amount),
        },
        'item_details': items,
        'customer_details': customer_details,
        'callbacks': {
            'finish': settings.MIDTRANS_FINISH_URL,
        },
    }
    result = _midtrans_snap_client().create_transaction(params)
    order.midtrans_token = result['token']
    order.midtrans_redirect_url = result.get('redirect_url', '')
    order.save(update_fields=['midtrans_token', 'midtrans_redirect_url', 'updated_at'])
    return result


def checkout_view(request):
    """Simpan order lalu arahkan pelanggan ke halaman pembayaran Midtrans Snap."""
    # Wajib login / daftar akun sebelum checkout
    if not request.user.is_authenticated:
        messages.info(request, 'Silakan masuk atau buat akun baru terlebih dahulu untuk melanjutkan proses checkout.')
        return redirect(f"/login/?next=/checkout/")

    cart = request.session.get('cart', {})
    if not isinstance(cart, dict) or not cart:
        messages.warning(request, 'Keranjang belanja Anda masih kosong. Silakan pilih menu terlebih dahulu.')
        return redirect('menu')

    subtotal = sum(int(item.get('subtotal', 0)) for item in cart.values())
    total_items = sum(int(item.get('quantity', 1)) for item in cart.values())

    if request.method == 'POST':
        customer_name = request.POST.get('customer_name', '').strip()
        customer_phone = request.POST.get('customer_phone', '').strip()
        order_type = request.POST.get('order_type', 'Delivery')
        delivery_address = request.POST.get('delivery_address', '').strip()
        notes = request.POST.get('notes', '').strip()

        if not customer_name or not customer_phone:
            messages.error(request, 'Nama pemesan dan nomor WhatsApp aktif wajib diisi!')
            return redirect('checkout')
        if subtotal <= 0:
            messages.error(request, 'Total pembayaran tidak valid.')
            return redirect('cart')

        order_number = f"YM-{timezone.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
        note_parts = [f'Tipe: {order_type}']
        if order_type == 'Delivery' and delivery_address:
            note_parts.append(f'Alamat: {delivery_address}')
        if notes:
            note_parts.append(f'Catatan: {notes}')

        order = Order.objects.create(
            order_number=order_number,
            customer=request.user if request.user.is_authenticated else None,
            customer_name=customer_name,
            customer_phone=customer_phone,
            notes=' | '.join(note_parts),
            total_amount=int(subtotal),
            status='PENDING',
            payment_status='UNPAID',
        )

        for item in cart.values():
            product_obj = Product.objects.filter(id=item.get('product_id')).first()
            item_desc = f"{item.get('name', 'Produk')} ({item.get('size', 'Reguler')})"
            options = []
            if item.get('sugar') and item.get('sugar') != 'Normal':
                options.append(f"Gula: {item['sugar']}")
            if item.get('ice') and item.get('ice') != 'Normal':
                options.append(f"Es: {item['ice']}")
            if item.get('notes'):
                options.append(f"Cat: {item['notes']}")
            if options:
                item_desc += f" [{', '.join(options)}]"
            OrderItem.objects.create(
                order=order,
                product=product_obj,
                product_name=item_desc,
                price=int(item['price']),
                quantity=int(item['quantity']),
            )

        if request.user.is_authenticated:
            profile, _ = UserProfile.objects.get_or_create(user=request.user)
            if customer_phone and not profile.phone:
                profile.phone = customer_phone
            if delivery_address and not profile.default_address:
                profile.default_address = delivery_address
            profile.save()

        ActivityLog.objects.create(
            user=request.user if request.user.is_authenticated else None,
            action=f'Pesanan baru #{order.order_number} dari {customer_name} (Rp {order.total_amount:,})',
            category='Pesanan',
        )

        payment_method = request.POST.get('payment_method', 'midtrans')
        request.session['cart'] = {}
        request.session['last_order_number'] = order.order_number
        request.session.modified = True

        if payment_method == 'cod':
            order.payment_type = 'Tunai / COD (Bayar di Tempat)'
            order.status = 'PROCESSING'
            order.save(update_fields=['payment_type', 'status', 'updated_at'])
            messages.success(request, f'Pesanan #{order.order_number} berhasil dibuat dengan metode Bayar di Tempat (COD)!')
            return redirect('order_success', order_number=order.order_number)

        return redirect('order_payment', order_number=order.order_number)

    prefilled_name = prefilled_phone = prefilled_address = ''
    if request.user.is_authenticated:
        prefilled_name = f'{request.user.first_name} {request.user.last_name}'.strip() or request.user.username
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        prefilled_phone = profile.phone or ''
        prefilled_address = profile.default_address or ''

    return render(request, 'store/checkout.html', {
        'cart': cart, 'subtotal': subtotal, 'grand_total': subtotal,
        'total_items': total_items, 'prefilled_name': prefilled_name,
        'prefilled_phone': prefilled_phone, 'prefilled_address': prefilled_address,
    })


def order_payment_view(request, order_number):
    order = get_object_or_404(Order, order_number=order_number)
    if not (request.user.is_authenticated and order.customer_id == request.user.id) and request.session.get('last_order_number') != order.order_number:
        return HttpResponse('Pesanan tidak ditemukan.', status=404)
    if order.payment_status == 'PAID':
        return redirect('order_success', order_number=order.order_number)

    # Tangani jika user memilih ubah ke Bayar Tunai / COD di halaman payment
    if request.method == 'POST' and request.POST.get('action') == 'cod':
        order.payment_type = 'Tunai / COD (Bayar di Tempat)'
        if order.status == 'PENDING':
            order.status = 'PROCESSING'
        order.save(update_fields=['payment_type', 'status', 'updated_at'])
        messages.success(request, 'Metode pembayaran diubah menjadi Bayar Tunai / COD.')
        return redirect('order_success', order_number=order.order_number)

    server_key = getattr(settings, 'MIDTRANS_SERVER_KEY', '')
    has_valid_key = server_key and not server_key.startswith('SB-Mid-server-GANTI') and not server_key.startswith('SB-Mid-server-ISI')

    try:
        if not order.midtrans_token and has_valid_key:
            _create_midtrans_transaction(order)
    except Exception as e:
        logging.exception('Gagal membuat transaksi Midtrans untuk %s', order.order_number)
        messages.error(request, f'Belum berhasil menghubungi Midtrans: {e}. Periksa konfigurasi API Key Sandbox.')

    client_key = getattr(settings, 'MIDTRANS_CLIENT_KEY', '')
    if client_key.startswith('SB-Mid-client-GANTI') or client_key.startswith('SB-Mid-client-ISI'):
        client_key = ''

    return render(request, 'store/payment.html', {
        'order': order,
        'snap_token': order.midtrans_token,
        'midtrans_client_key': client_key,
        'midtrans_is_production': getattr(settings, 'MIDTRANS_IS_PRODUCTION', False),
        'debug_mode': settings.DEBUG,
    })


def simulate_payment_view(request, order_number):
    """Simulasi pembayaran Midtrans berhasil untuk pengujian / development."""
    order = get_object_or_404(Order, order_number=order_number)
    if not (request.user.is_authenticated and order.customer_id == request.user.id) and request.session.get('last_order_number') != order.order_number:
        return HttpResponse('Pesanan tidak ditemukan.', status=404)

    order.payment_status = 'PAID'
    if order.status == 'PENDING':
        order.status = 'PROCESSING'
    order.payment_type = 'Simulasi Midtrans (Sandbox Test)'
    order.save(update_fields=['payment_status', 'status', 'payment_type', 'updated_at'])

    ActivityLog.objects.create(
        user=request.user if request.user.is_authenticated else None,
        action=f'Simulasi pembayaran berhasil untuk pesanan #{order.order_number}',
        category='Pesanan',
    )
    messages.success(request, 'Pembayaran Midtrans berhasil diverifikasi! Pesanan sedang diproses.')
    return redirect('order_success', order_number=order.order_number)


@csrf_exempt
def midtrans_notification_view(request):
    """Webhook Midtrans: verifikasi signature lalu perbarui status pesanan."""
    if request.method != 'POST':
        return HttpResponseBadRequest('POST required')
    signature_secret = getattr(settings, 'MIDTRANS_SIGNATURE_KEY', '')
    if not signature_secret:
        return HttpResponseServerError('MIDTRANS_SIGNATURE_KEY belum dikonfigurasi')
    try:
        payload = json.loads(request.body.decode('utf-8'))
        order_id = str(payload['order_id'])
        status_code = str(payload['status_code'])
        gross_amount = str(payload['gross_amount'])
        received_signature = str(payload['signature_key'])
    except (ValueError, KeyError, TypeError):
        return HttpResponseBadRequest('Invalid notification payload')

    raw = f'{order_id}{status_code}{gross_amount}{signature_secret}'
    expected = hashlib.sha512(raw.encode('utf-8')).hexdigest()
    if not hmac.compare_digest(expected, received_signature):
        return HttpResponse('Invalid signature', status=403)

    order = get_object_or_404(Order, order_number=order_id)
    try:
        # Cocokkan nominal tanpa konversi float agar tidak terkena pembulatan.
        if Decimal(gross_amount) != Decimal(order.total_amount):
            return HttpResponse('Amount mismatch', status=400)
    except (InvalidOperation, TypeError):
        return HttpResponseBadRequest('Invalid amount')

    transaction_status = payload.get('transaction_status', '')
    fraud_status = payload.get('fraud_status', '')
    order.midtrans_transaction_id = str(payload.get('transaction_id', ''))
    order.payment_type = str(payload.get('payment_type', ''))[:40]

    if transaction_status == 'settlement' or (transaction_status == 'capture' and fraud_status == 'accept'):
        order.payment_status = 'PAID'
        if order.status == 'PENDING':
            order.status = 'PROCESSING'
    elif transaction_status == 'pending':
        order.payment_status = 'PENDING'
    elif transaction_status in ('deny', 'cancel', 'expire', 'failure'):
        order.payment_status = transaction_status.upper()
        if order.status == 'PENDING':
            order.status = 'CANCELLED'

    order.save(update_fields=[
        'payment_status', 'midtrans_transaction_id', 'payment_type', 'status', 'updated_at'
    ])
    return JsonResponse({'status': 'ok'})


def order_success_view(request, order_number):
    order = get_object_or_404(Order, order_number=order_number)
    if not (request.user.is_authenticated and order.customer_id == request.user.id) and request.session.get('last_order_number') != order.order_number:
        return HttpResponse('Pesanan tidak ditemukan.', status=404)

    # Jika order belum berstatus PAID, coba cek langsung ke status API Midtrans
    if order.payment_status != 'PAID':
        server_key = getattr(settings, 'MIDTRANS_SERVER_KEY', '')
        if server_key and not server_key.startswith('SB-Mid-server-GANTI') and not server_key.startswith('SB-Mid-server-ISI'):
            try:
                snap = _midtrans_snap_client()
                tx_status = snap.transactions.status(order.order_number)
                tx_state = tx_status.get('transaction_status', '')
                fraud = tx_status.get('fraud_status', '')
                if tx_state == 'settlement' or (tx_state == 'capture' and fraud in ('', 'accept')):
                    order.payment_status = 'PAID'
                    if order.status == 'PENDING':
                        order.status = 'PROCESSING'
                    order.midtrans_transaction_id = str(tx_status.get('transaction_id', ''))
                    order.payment_type = str(tx_status.get('payment_type', ''))[:40]
                    order.save(update_fields=['payment_status', 'status', 'midtrans_transaction_id', 'payment_type', 'updated_at'])
            except Exception:
                pass

    return render(request, 'store/order_success.html', {'order': order})


def submit_testimonial(request):
    """
    Formulir pengiriman ulasan / testimoni pengunjung yang langsung tersimpan
    ke database (ContactMessage) dan tercatat di Log Aktivitas.
    """
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        phone = request.POST.get('phone', '').strip()
        email = request.POST.get('email', '').strip()
        rating = request.POST.get('rating', '5')
        message = request.POST.get('message', '').strip()

        if name and message:
            ContactMessage.objects.create(
                sender_name=name,
                sender_phone=phone,
                sender_email=email,
                subject=f"Ulasan Pelanggan (Bintang {rating} ⭐)",
                message=message,
                is_read=True
            )
            ActivityLog.objects.create(
                user=request.user if request.user.is_authenticated else None,
                action=f"Ulasan baru diterima dari: {name} (Bintang {rating})",
                category="Kotak Masuk & Ulasan"
            )
            messages.success(request, "Terima kasih! Ulasan Anda telah berhasil disimpan dan sangat berarti bagi Yellow Mango's.")
        else:
            messages.error(request, "Nama dan pesan ulasan wajib diisi!")

    return redirect('/#testimoni')


# ==========================================
# 4. AUTENTIKASI: USER & ADMIN
# ==========================================

def custom_login_view(request):
    """
    Halaman Login & Pendaftaran Akun Pelanggan (User Portal):
    - Mendukung Log In dengan Username atau Email
    - Mendukung Pendaftaran akun baru (Sign Up)
    - Mengembalikan user ke halaman tujuan sebelumnya (misal checkout)
    """
    error_message = None
    default_mode = request.GET.get('mode', 'login')
    next_url = request.GET.get('next') or request.POST.get('next') or 'index'

    if request.method == 'POST':
        action = request.POST.get('action')
        identifier = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        if action == 'signup':
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            phone = request.POST.get('phone', '').strip()
            confirm_password = request.POST.get('confirm_password', '')

            # Validasi input sign up
            if confirm_password and password != confirm_password:
                error_message = "Konfirmasi password tidak cocok!"
                default_mode = 'signup'
            elif User.objects.filter(username=identifier).exists() or User.objects.filter(email=identifier).exists():
                error_message = "Email atau Username sudah terdaftar, silakan gunakan yang lain."
                default_mode = 'signup'
            else:
                user = User.objects.create_user(
                    username=identifier,
                    email=identifier if '@' in identifier else '',
                    password=password,
                    first_name=first_name,
                    last_name=last_name
                )
                if phone:
                    UserProfile.objects.get_or_create(user=user, defaults={'phone': phone})
                login(request, user)
                ActivityLog.objects.create(
                    user=user,
                    action=f"Pendaftaran akun pelanggan baru: {user.username}",
                    category="Pengguna & Staf"
                )
                messages.success(request, f"Selamat datang di Yellow Mango's, {user.first_name or user.username}!")
                if next_url and next_url != 'index':
                    return redirect(next_url)
                return redirect('index')
        else:
            # Login: cek username langsung atau via email (case-insensitive)
            target_username = identifier
            if '@' in identifier:
                found_user = User.objects.filter(email__iexact=identifier).first()
                if found_user:
                    target_username = found_user.username

            user = authenticate(request, username=target_username, password=password)
            if user is not None:
                login(request, user)
                messages.success(request, f"Halo, {user.first_name or user.username}! Anda berhasil masuk.")
                if (user.is_staff or user.is_superuser) and next_url in ('index', '/', ''):
                    return redirect('admin_dashboard')
                if next_url and next_url != 'index':
                    return redirect(next_url)
                return redirect('index')
            else:
                error_message = "Email/Username atau password yang Anda masukkan salah!"
                default_mode = 'login'

    return render(request, 'store/login.html', {
        'error': error_message,
        'mode': default_mode,
        'next': next_url,
    })


def google_login_view(request):
    """
    Mengarahkan pengguna ke Google OAuth2 Authorization endpoint.
    """
    client_id = getattr(settings, 'GOOGLE_CLIENT_ID', '')
    if not client_id:
        messages.warning(
            request,
            "Integrasi Google Login sedang disiapkan. Harap atur GOOGLE_CLIENT_ID dan GOOGLE_CLIENT_SECRET di file .env atau Vercel."
        )
        return redirect('login')

    next_url = request.GET.get('next') or request.META.get('HTTP_REFERER') or '/'
    request.session['google_auth_next'] = next_url

    redirect_uri = request.build_absolute_uri(reverse('google_login_callback'))
    if request.is_secure() or getattr(settings, 'VERCEL', False) or os.getenv('VERCEL') == '1':
        redirect_uri = redirect_uri.replace('http://', 'https://')

    params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'openid email profile',
        'access_type': 'online',
        'prompt': 'select_account',
    }
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"
    return redirect(auth_url)


def google_login_callback_view(request):
    """
    Menerima authorization code dari Google OAuth, menukarkannya dengan token,
    mengambil data profil akun Google, lalu membuat / login user Django.
    """
    code = request.GET.get('code')
    error = request.GET.get('error')

    if error or not code:
        messages.error(request, 'Proses masuk dengan Google dibatalkan atau terjadi kesalahan.')
        return redirect('login')

    client_id = getattr(settings, 'GOOGLE_CLIENT_ID', '')
    client_secret = getattr(settings, 'GOOGLE_CLIENT_SECRET', '')
    redirect_uri = request.build_absolute_uri(reverse('google_login_callback'))
    if request.is_secure() or getattr(settings, 'VERCEL', False) or os.getenv('VERCEL') == '1':
        redirect_uri = redirect_uri.replace('http://', 'https://')

    # Tukar authorization code dengan access token
    token_url = 'https://oauth2.googleapis.com/token'
    token_payload = urllib.parse.urlencode({
        'code': code,
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': redirect_uri,
        'grant_type': 'authorization_code',
    }).encode('utf-8')

    try:
        req = urllib.request.Request(token_url, data=token_payload, method='POST')
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        with urllib.request.urlopen(req, timeout=10) as response:
            token_res = json.loads(response.read().decode('utf-8'))
            access_token = token_res.get('access_token')

        if not access_token:
            messages.error(request, 'Gagal mendapatkan token autentikasi dari Google.')
            return redirect('login')

        # Ambil data profil dari Google UserInfo endpoint
        userinfo_url = 'https://www.googleapis.com/oauth2/v3/userinfo'
        user_req = urllib.request.Request(userinfo_url)
        user_req.add_header('Authorization', f'Bearer {access_token}')
        with urllib.request.urlopen(user_req, timeout=10) as user_res:
            user_data = json.loads(user_res.read().decode('utf-8'))

    except Exception as e:
        messages.error(request, f'Gagal menghubungi server Google: {str(e)}')
        return redirect('login')

    email = user_data.get('email', '').strip().lower()
    given_name = user_data.get('given_name') or user_data.get('name', 'Pelanggan')
    family_name = user_data.get('family_name', '')

    if not email:
        messages.error(request, 'Akun Google tidak menyediakan alamat email yang valid.')
        return redirect('login')

    # Cari user berdasarkan email atau buat akun baru
    user = User.objects.filter(email__iexact=email).first()
    if not user:
        base_username = email.split('@')[0]
        username = base_username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}_{counter}"
            counter += 1

        user = User.objects.create_user(
            username=username,
            email=email,
            first_name=given_name,
            last_name=family_name
        )
        user.set_unusable_password()
        user.save()
    else:
        if not user.first_name and given_name:
            user.first_name = given_name
            user.save()

    UserProfile.objects.get_or_create(user=user)

    # Login pengguna
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')

    ActivityLog.objects.create(
        user=user,
        action=f"Pengguna masuk menggunakan Akun Google: {email}",
        category="Autentikasi"
    )
    messages.success(request, f"Halo {user.first_name or user.username}! Anda berhasil masuk dengan akun Google.")

    next_url = request.session.pop('google_auth_next', None) or 'index'
    if (user.is_staff or user.is_superuser) and next_url in ('index', '/', ''):
        return redirect('admin_dashboard')
    if next_url and next_url != 'index':
        return redirect(next_url)
    return redirect('index')


def custom_admin_login(request):
    """
    Halaman Login Khusus Administrator & Staff Yellow Mango's:
    - Hanya memperbolehkan akun dengan hak akses is_staff / is_superuser
    - Mengarahkan langsung ke dashboard admin
    """
    error = None
    if request.method == 'POST':
        user_name = request.POST.get('username', '').strip()
        pass_word = request.POST.get('password', '')
        user = authenticate(request, username=user_name, password=pass_word)

        if user is not None:
            if user.is_staff or user.is_superuser:
                login(request, user)
                ActivityLog.objects.create(
                    user=user,
                    action=f"Admin {user.username} login ke Dashboard",
                    category="Sistem"
                )
                return redirect('admin_dashboard')
            else:
                error = "Akun Anda terdaftar sebagai pelanggan biasa, bukan administrator."
        else:
            error = "Username atau password admin salah!"

    return render(request, 'store/custom_login.html', {'error': error})


def custom_logout_view(request):
    """
    Fungsi Logout untuk Pelanggan & Staf:
    - Menghapus sesi login
    - Mengembalikan ke halaman utama dengan pesan informasi
    """
    user_name = request.user.username if request.user.is_authenticated else "Pengguna"
    logout(request)
    messages.info(request, f"Sampai jumpa lagi, {user_name}. Anda telah berhasil keluar.")
    return redirect('index')


# ==========================================
# 5. HALAMAN ARTIKEL & BLOG RESMI
# ==========================================

def articles_list_view(request):
    """
    Halaman Daftar Artikel & Blog Publik:
    - Menampilkan artikel yang diterbitkan (is_published=True)
    - Pencarian artikel berdasarkan kata kunci (judul, isi, tags)
    - Filter artikel berdasarkan kategori
    """
    q = request.GET.get('q', '').strip()
    category = request.GET.get('category', '').strip()

    articles = Article.objects.filter(is_published=True).order_by('-created_at')

    if q:
        articles = articles.filter(
            Q(title__icontains=q) | Q(content__icontains=q) | Q(tags__icontains=q)
        )

    if category and category != 'ALL':
        articles = articles.filter(category=category)

    # Ambil daftar kategori artikel yang unik dari database
    category_list = Article.objects.filter(is_published=True).values_list('category', flat=True).distinct()

    context = {
        'articles': articles,
        'category_list': category_list,
        'selected_category': category,
        'search_query': q,
        'total_articles': articles.count(),
    }
    return render(request, 'store/articles_list.html', context)


def article_detail_view(request, slug):
    """
    Halaman Detail Artikel / Blog:
    - Membaca artikel lengkap dari database
    - Menampilkan thumbnail, tanggal terbit, penulis, dan isi
    - Menampilkan rekomendasi artikel terkait
    """
    article = get_object_or_404(Article, slug=slug, is_published=True)
    related_articles = Article.objects.filter(is_published=True).exclude(id=article.id)[:3]

    context = {
        'article': article,
        'related_articles': related_articles,
    }
    return render(request, 'store/article_detail.html', context)


# ==========================================
# 6. DASHBOARD & PROFIL PENGGUNA (USER PROFILE & WEB SETTINGS)
# ==========================================

@login_required(login_url='/login/')
def user_profile_view(request):
    """
    Halaman Dashboard & Profil Pelanggan:
    - Informasi identitas pengguna & ringkasan aktivitas belanja
    - Riwayat seluruh pesanan (Order) yang dilakukan oleh pengguna
    - Pengaturan profil (Nama depan, nama belakang, email, WhatsApp, alamat pengiriman default)
    - Pengaturan keamanan (ganti kata sandi)
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    user_orders = Order.objects.filter(customer=request.user).order_by('-created_at')

    total_orders = user_orders.count()
    total_spent = sum(order.total_amount for order in user_orders)
    active_orders = user_orders.filter(status__in=['PENDING', 'PROCESSING', 'READY']).count()

    active_tab = request.GET.get('tab', 'overview')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'update_profile':
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            email = request.POST.get('email', '').strip()
            phone = request.POST.get('phone', '').strip()
            default_address = request.POST.get('default_address', '').strip()

            # Perbarui nama & email
            request.user.first_name = first_name
            request.user.last_name = last_name
            if email:
                request.user.email = email
            request.user.save()

            # Perbarui foto profil jika diunggah
            if 'avatar' in request.FILES:
                profile.avatar = request.FILES['avatar']

            # Perbarui nomor telepon dan alamat default pada profil
            profile.phone = phone
            profile.default_address = default_address
            profile.save()

            ActivityLog.objects.create(
                user=request.user,
                action=f"Pengguna {request.user.username} memperbarui data profil & alamat",
                category="Profil Pengguna"
            )
            messages.success(request, "Profil dan alamat pengiriman Anda berhasil disimpan!")
            return redirect('/profil/?tab=pengaturan')

        elif action == 'change_password':
            current_password = request.POST.get('current_password', '')
            new_password = request.POST.get('new_password', '')
            confirm_password = request.POST.get('confirm_password', '')

            if not request.user.check_password(current_password):
                messages.error(request, "Kata sandi saat ini (lama) tidak sesuai!")
                return redirect('/profil/?tab=keamanan')
            elif new_password != confirm_password:
                messages.error(request, "Konfirmasi password baru tidak cocok!")
                return redirect('/profil/?tab=keamanan')
            elif len(new_password) < 6:
                messages.error(request, "Password baru minimal 6 karakter!")
                return redirect('/profil/?tab=keamanan')
            else:
                request.user.set_password(new_password)
                request.user.save()
                update_session_auth_hash(request, request.user)
                ActivityLog.objects.create(
                    user=request.user,
                    action=f"Pengguna {request.user.username} memperbarui kata sandi akun",
                    category="Keamanan Akun"
                )
                messages.success(request, "Kata sandi akun Anda berhasil diperbarui!")
                return redirect('/profil/?tab=keamanan')

        elif action == 'send_user_message':
            subject = request.POST.get('subject', 'Pertanyaan Pelanggan').strip()
            message_text = request.POST.get('message', '').strip()

            if message_text:
                ContactMessage.objects.create(
                    customer=request.user,
                    sender_name=request.user.get_full_name() or request.user.username,
                    sender_email=request.user.email or '',
                    sender_phone=profile.phone or '',
                    subject=subject,
                    message=message_text,
                )
                ActivityLog.objects.create(
                    user=request.user,
                    action=f"Pengguna {request.user.username} mengirim pesan bantuan: {subject}",
                    category="Pesan & Chat"
                )
                messages.success(request, "Pesan Anda berhasil dikirim! Tim Yellow Mango's akan segera merespons.")
            else:
                messages.error(request, "Isi pesan tidak boleh kosong!")
            return redirect('/profil/?tab=pesan')

    user_messages = ContactMessage.objects.filter(customer=request.user).order_by('-created_at')
    unread_messages_count = user_messages.filter(is_read=True).exclude(admin_reply__isnull=True).exclude(admin_reply__exact='').count()

    context = {
        'profile': profile,
        'orders': user_orders,
        'total_orders': total_orders,
        'total_spent': total_spent,
        'active_orders': active_orders,
        'active_tab': active_tab,
        'user_messages': user_messages,
        'unread_messages_count': unread_messages_count,
    }
    return render(request, 'store/user_profile.html', context)


# ==========================================
# 5. HALAMAN INFORMASI & LEGALITAS
# ==========================================

def location_view(request):
    return render(request, 'store/location.html')

def about_view(request):
    return render(request, 'store/about.html')

def terms_view(request):
    return render(request, 'store/legal/terms.html')

def privacy_view(request):
    return render(request, 'store/legal/privacy.html')

def disclaimer_view(request):
    return render(request, 'store/legal/disclaimer.html')

def hours_view(request):
    return render(request, 'store/legal/hours.html')

def faq_view(request):
    return render(request, 'store/legal/faq.html')

def page_detail(request, slug):
    page = get_object_or_404(Page, slug=slug, is_published=True)
    return render(request, 'store/page_detail.html', {'page': page})


# ==========================================
# 6. PANEL ADMIN KUSTOM (DASHBOARD & MANAGEMENT)
# ==========================================

@login_required(login_url='/custom-admin-login/')
def admin_dashboard(request):
    context = {
        'total_products': Product.objects.count(),
        'total_orders': Order.objects.count(),
        'total_users': User.objects.count(),
        'total_articles': Article.objects.count(),
        'recent_activities': ActivityLog.objects.all().order_by('-created_at')[:6],
        'recent_orders': Order.objects.all().order_by('-created_at')[:5],
    }
    return render(request, 'store/admin_panel/dashboard.html', context)


@login_required(login_url='/custom-admin-login/')
def admin_products(request):
    if request.method == 'POST':
        action = request.POST.get('action')

        # TAMBAH MENU BARU
        if action == 'add':
            name = request.POST.get('name')
            category = request.POST.get('category', 'Smoothies & Jus')
            price = request.POST.get('price')
            description = request.POST.get('description')
            badge_primary = request.POST.get('badge_primary', 'NONE')
            badge_secondary = request.POST.get('badge_secondary', 'NONE')
            image = request.FILES.get('image')
            image_url = request.POST.get('image_url')
            is_available = request.POST.get('is_available') == 'on'

            Product.objects.create(
                name=name,
                category=category,
                price=price,
                description=description,
                badge_primary=badge_primary,
                badge_secondary=badge_secondary,
                image=image,
                image_url=image_url,
                is_available=is_available
            )
            ActivityLog.objects.create(
                user=request.user,
                action=f"Menambahkan menu baru: {name} (Kategori: {category})",
                category="Produk & Menu"
            )
            messages.success(request, f"Menu '{name}' berhasil ditambahkan!")
            return redirect('admin_products')

        # EDIT MENU
        elif action == 'edit':
            product_id = request.POST.get('product_id')
            product = get_object_or_404(Product, id=product_id)
            product.name = request.POST.get('name')
            product.category = request.POST.get('category', product.category)
            product.price = request.POST.get('price')
            product.description = request.POST.get('description')
            product.badge_primary = request.POST.get('badge_primary', 'NONE')
            product.badge_secondary = request.POST.get('badge_secondary', 'NONE')
            product.image_url = request.POST.get('image_url')
            product.is_available = request.POST.get('is_available') == 'on'
            
            if request.FILES.get('image'):
                product.image = request.FILES.get('image')
                
            product.save()
            ActivityLog.objects.create(
                user=request.user,
                action=f"Memperbarui menu: {product.name}",
                category="Produk & Menu"
            )
            messages.success(request, f"Menu '{product.name}' berhasil diperbarui!")
            return redirect('admin_products')

        # HAPUS MENU
        elif action == 'delete':
            product_id = request.POST.get('product_id')
            product = get_object_or_404(Product, id=product_id)
            nama_menu = product.name
            product.delete()
            ActivityLog.objects.create(
                user=request.user,
                action=f"Menghapus menu: {nama_menu}",
                category="Produk & Menu"
            )
            messages.success(request, f"Menu '{nama_menu}' berhasil dihapus.")
            return redirect('admin_products')

    products = Product.objects.all().order_by('-id')
    context = {
        'products': products,
        'badge_choices': Product.BADGE_CHOICES,
        'category_choices': Product.CATEGORY_CHOICES,
    }
    return render(request, 'store/admin_panel/products.html', context)


@login_required(login_url='/custom-admin-login/')
def admin_orders(request):
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'update_status':
            order_id = request.POST.get('order_id')
            new_status = request.POST.get('status')
            order = get_object_or_404(Order, id=order_id)
            order.status = new_status
            order.save()

            ActivityLog.objects.create(
                user=request.user,
                action=f"Mengubah status pesanan #{order.order_number} menjadi {order.get_status_display()}",
                category="Pesanan"
            )
            messages.success(request, f"Status pesanan #{order.order_number} diperbarui!")
            return redirect('admin_orders')

        elif action == 'add_manual':
            customer_name = request.POST.get('customer_name')
            customer_phone = request.POST.get('customer_phone')
            product_id = request.POST.get('product_id')
            quantity = int(request.POST.get('quantity', 1))
            notes = request.POST.get('notes', '')

            product = get_object_or_404(Product, id=product_id)
            total_amount = product.price * quantity
            order_number = f"YM-{uuid.uuid4().hex[:6].upper()}"

            order = Order.objects.create(
                order_number=order_number,
                customer_name=customer_name,
                customer_phone=customer_phone,
                notes=notes,
                total_amount=total_amount,
                status='PROCESSING'
            )

            OrderItem.objects.create(
                order=order,
                product=product,
                product_name=product.name,
                price=product.price,
                quantity=quantity
            )

            ActivityLog.objects.create(
                user=request.user,
                action=f"Mencatat pesanan manual #{order_number} ({customer_name})",
                category="Pesanan"
            )
            messages.success(request, f"Pesanan #{order_number} berhasil dicatat!")
            return redirect('admin_orders')

        elif action == 'delete':
            order_id = request.POST.get('order_id')
            order = get_object_or_404(Order, id=order_id)
            no_pesanan = order.order_number
            order.delete()

            ActivityLog.objects.create(
                user=request.user,
                action=f"Menghapus pesanan #{no_pesanan}",
                category="Pesanan"
            )
            messages.success(request, f"Pesanan #{no_pesanan} telah dihapus.")
            return redirect('admin_orders')

    status_filter = request.GET.get('status', 'ALL')
    if status_filter != 'ALL':
        orders = Order.objects.filter(status=status_filter).prefetch_related('items')
    else:
        orders = Order.objects.all().prefetch_related('items')

    context = {
        'orders': orders,
        'status_choices': Order.STATUS_CHOICES,
        'status_filter': status_filter,
        'products': Product.objects.filter(is_available=True),
    }
    return render(request, 'store/admin_panel/orders.html', context)


@login_required(login_url='/custom-admin-login/')
def admin_pages(request):
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'add':
            title = request.POST.get('title')
            slug_input = request.POST.get('slug')
            content = request.POST.get('content')
            is_published = request.POST.get('is_published') == 'on'

            slug = slugify(slug_input) if slug_input else slugify(title)

            Page.objects.create(
                title=title,
                slug=slug,
                content=content,
                is_published=is_published
            )
            ActivityLog.objects.create(
                user=request.user,
                action=f"Membuat halaman baru: {title}",
                category="Page Builder"
            )
            messages.success(request, f"Halaman '{title}' berhasil dibuat!")
            return redirect('admin_pages')

        elif action == 'edit':
            page_id = request.POST.get('page_id')
            page = get_object_or_404(Page, id=page_id)
            page.title = request.POST.get('title')
            slug_input = request.POST.get('slug')
            page.slug = slugify(slug_input) if slug_input else slugify(page.title)
            page.content = request.POST.get('content')
            page.is_published = request.POST.get('is_published') == 'on'
            page.save()

            ActivityLog.objects.create(
                user=request.user,
                action=f"Memperbarui halaman: {page.title}",
                category="Page Builder"
            )
            messages.success(request, f"Halaman '{page.title}' berhasil diperbarui!")
            return redirect('admin_pages')

        elif action == 'delete':
            page_id = request.POST.get('page_id')
            page = get_object_or_404(Page, id=page_id)
            judul = page.title
            page.delete()

            ActivityLog.objects.create(
                user=request.user,
                action=f"Menghapus halaman: {judul}",
                category="Page Builder"
            )
            messages.success(request, f"Halaman '{judul}' telah dihapus.")
            return redirect('admin_pages')

    pages = Page.objects.all().order_by('-updated_at')
    return render(request, 'store/admin_panel/pages.html', {'pages': pages})


@login_required(login_url='/custom-admin-login/')
def admin_articles(request):
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'add':
            title = request.POST.get('title')
            category = request.POST.get('category', 'Tips & Kuliner')
            tags = request.POST.get('tags', '')
            content = request.POST.get('content')
            thumbnail = request.FILES.get('thumbnail')
            is_published = request.POST.get('is_published') == 'on'

            Article.objects.create(
                title=title,
                category=category,
                tags=tags,
                content=content,
                thumbnail=thumbnail,
                author=request.user,
                is_published=is_published
            )
            ActivityLog.objects.create(
                user=request.user,
                action=f"Membuat artikel baru: {title}",
                category="Artikel & Blog"
            )
            messages.success(request, f"Artikel '{title}' berhasil diterbitkan!")
            return redirect('admin_articles')

        elif action == 'edit':
            article_id = request.POST.get('article_id')
            article = get_object_or_404(Article, id=article_id)
            article.title = request.POST.get('title')
            article.category = request.POST.get('category', 'Tips & Kuliner')
            article.tags = request.POST.get('tags', '')
            article.content = request.POST.get('content')
            article.is_published = request.POST.get('is_published') == 'on'

            if request.FILES.get('thumbnail'):
                article.thumbnail = request.FILES.get('thumbnail')

            article.save()
            ActivityLog.objects.create(
                user=request.user,
                action=f"Memperbarui artikel: {article.title}",
                category="Artikel & Blog"
            )
            messages.success(request, f"Artikel '{article.title}' berhasil diperbarui!")
            return redirect('admin_articles')

        elif action == 'delete':
            article_id = request.POST.get('article_id')
            article = get_object_or_404(Article, id=article_id)
            jud = article.title
            article.delete()

            ActivityLog.objects.create(
                user=request.user,
                action=f"Menghapus artikel: {jud}",
                category="Artikel & Blog"
            )
            messages.success(request, f"Artikel '{jud}' telah dihapus.")
            return redirect('admin_articles')

    articles = Article.objects.all().order_by('-created_at')
    return render(request, 'store/admin_panel/articles.html', {'articles': articles})


@login_required(login_url='/custom-admin-login/')
def admin_announcements(request):
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'add':
            title = request.POST.get('title')
            announcement_type = request.POST.get('announcement_type', 'PROMO')
            description = request.POST.get('description')
            event_date = request.POST.get('event_date') or None
            banner = request.FILES.get('banner') or request.FILES.get('image')
            is_active = request.POST.get('is_active') == 'on'

            Announcement.objects.create(
                title=title,
                announcement_type=announcement_type,
                description=description,
                event_date=event_date,
                banner=banner,
                is_active=is_active
            )
            ActivityLog.objects.create(
                user=request.user,
                action=f"Membuat pengumuman/event baru: {title}",
                category="Event & Promo"
            )
            messages.success(request, f"Pengumuman '{title}' berhasil ditambahkan!")
            return redirect('admin_announcements')

        elif action == 'edit':
            ann_id = request.POST.get('announcement_id')
            ann = get_object_or_404(Announcement, id=ann_id)
            ann.title = request.POST.get('title')
            ann.announcement_type = request.POST.get('announcement_type', 'PROMO')
            ann.description = request.POST.get('description')
            
            event_date = request.POST.get('event_date')
            ann.event_date = event_date if event_date else None
            ann.is_active = request.POST.get('is_active') == 'on'

            if request.FILES.get('banner'):
                ann.banner = request.FILES.get('banner')
            elif request.FILES.get('image'):
                ann.banner = request.FILES.get('image')

            ann.save()
            ActivityLog.objects.create(
                user=request.user,
                action=f"Memperbarui pengumuman/event: {ann.title}",
                category="Event & Promo"
            )
            messages.success(request, f"Pengumuman '{ann.title}' berhasil diperbarui!")
            return redirect('admin_announcements')

        elif action == 'delete':
            ann_id = request.POST.get('announcement_id')
            ann = get_object_or_404(Announcement, id=ann_id)
            judul = ann.title
            ann.delete()

            ActivityLog.objects.create(
                user=request.user,
                action=f"Menghapus pengumuman/event: {judul}",
                category="Event & Promo"
            )
            messages.success(request, f"Pengumuman '{judul}' telah dihapus.")
            return redirect('admin_announcements')

    announcements = Announcement.objects.all().order_by('-created_at')
    context = {
        'announcements': announcements,
        'type_choices': Announcement.TYPE_CHOICES,
    }
    return render(request, 'store/admin_panel/announcements.html', context)


@login_required(login_url='/custom-admin-login/')
def admin_media(request):
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'upload':
            title = request.POST.get('title')
            file_type = request.POST.get('file_type', 'IMAGE')
            file_obj = request.FILES.get('file')

            if file_obj:
                MediaAsset.objects.create(
                    title=title,
                    file_type=file_type,
                    file=file_obj,
                    uploaded_by=request.user
                )
                ActivityLog.objects.create(
                    user=request.user,
                    action=f"Mengunggah berkas media: {title}",
                    category="Media Library"
                )
                messages.success(request, f"Berkas '{title}' berhasil diunggah!")
            else:
                messages.error(request, "Pilih berkas yang ingin diunggah terlebih dahulu.")
            
            return redirect('admin_media')

        elif action == 'delete':
            media_id = request.POST.get('media_id')
            media = get_object_or_404(MediaAsset, id=media_id)
            nama_berkas = media.title
            media.delete()

            ActivityLog.objects.create(
                user=request.user,
                action=f"Menghapus berkas media: {nama_berkas}",
                category="Media Library"
            )
            messages.success(request, f"Berkas '{nama_berkas}' telah dihapus.")
            return redirect('admin_media')

    media_list = MediaAsset.objects.all().order_by('-uploaded_at')
    type_choices = [
        ('IMAGE', 'Gambar'),
        ('VIDEO', 'Video'),
        ('DOCUMENT', 'Dokumen PDF / File'),
    ]

    context = {
        'media_list': media_list,
        'type_choices': type_choices,
    }
    return render(request, 'store/admin_panel/media.html', context)


@login_required(login_url='/custom-admin-login/')
def admin_users(request):
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'add':
            username = request.POST.get('username')
            email = request.POST.get('email')
            password = request.POST.get('password')
            is_staff = request.POST.get('is_staff') == 'on'
            is_superuser = request.POST.get('is_superuser') == 'on'

            if User.objects.filter(username=username).exists():
                messages.error(request, f"Username '{username}' sudah digunakan.")
            else:
                user = User.objects.create_user(username=username, email=email, password=password)
                user.is_staff = is_staff
                user.is_superuser = is_superuser
                user.save()

                ActivityLog.objects.create(
                    user=request.user,
                    action=f"Membuat akun pengguna/staf baru: {username}",
                    category="Pengguna & Staf"
                )
                messages.success(request, f"Akun '{username}' berhasil ditambahkan!")
            return redirect('admin_users')

        elif action == 'delete':
            user_id = request.POST.get('user_id')
            target_user = get_object_or_404(User, id=user_id)
            
            if target_user == request.user:
                messages.error(request, "Anda tidak dapat menghapus akun yang sedang Anda gunakan.")
            else:
                uname = target_user.username
                target_user.delete()
                ActivityLog.objects.create(
                    user=request.user,
                    action=f"Menghapus akun pengguna: {uname}",
                    category="Pengguna & Staf"
                )
                messages.success(request, f"Akun '{uname}' telah dihapus.")
            return redirect('admin_users')

    users_list = User.objects.all().order_by('-date_joined')
    return render(request, 'store/admin_panel/users.html', {'users_list': users_list})


@login_required(login_url='/custom-admin-login/')
def admin_messages(request):
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'toggle_read':
            msg_id = request.POST.get('message_id')
            msg = get_object_or_404(ContactMessage, id=msg_id)
            msg.is_read = not msg.is_read
            msg.save()
            messages.success(request, f"Status pesan dari {msg.sender_name} diperbarui!")
            return redirect('admin_messages')

        elif action == 'reply':
            msg_id = request.POST.get('message_id')
            admin_reply = request.POST.get('admin_reply', '').strip()
            msg = get_object_or_404(ContactMessage, id=msg_id)
            msg.admin_reply = admin_reply
            msg.is_read = True
            msg.save()

            ActivityLog.objects.create(
                user=request.user,
                action=f"Membalas pesan dari: {msg.sender_name}",
                category="Kotak Masuk & Ulasan"
            )
            messages.success(request, f"Balasan untuk '{msg.sender_name}' berhasil disimpan!")
            return redirect('admin_messages')

        elif action == 'delete':
            msg_id = request.POST.get('message_id')
            msg = get_object_or_404(ContactMessage, id=msg_id)
            pengirim = msg.sender_name
            msg.delete()

            ActivityLog.objects.create(
                user=request.user,
                action=f"Menghapus pesan dari: {pengirim}",
                category="Kotak Masuk & Ulasan"
            )
            messages.success(request, f"Pesan dari '{pengirim}' telah dihapus.")
            return redirect('admin_messages')

    messages_list = ContactMessage.objects.all().order_by('-created_at')
    return render(request, 'store/admin_panel/messages.html', {'messages_list': messages_list})


@login_required(login_url='/custom-admin-login/')
def admin_settings(request):
    try:
        setting = SiteSetting.objects.first()
        if not setting:
            setting = SiteSetting.objects.create()
    except Exception:
        setting = None

    if request.method == 'POST':
        if setting:
            if 'site_name' in request.POST:
                setting.site_name = request.POST.get('site_name')
            if 'tagline' in request.POST:
                setting.tagline = request.POST.get('tagline')
            if 'phone_primary' in request.POST:
                setting.phone_primary = request.POST.get('phone_primary')
            if 'outlet_address' in request.POST:
                setting.outlet_address = request.POST.get('outlet_address')
            if 'whatsapp_url' in request.POST:
                setting.whatsapp_url = request.POST.get('whatsapp_url')
            if request.FILES.get('logo'):
                setting.logo = request.FILES.get('logo')
            setting.save()

        ActivityLog.objects.create(
            user=request.user,
            action="Memperbarui pengaturan umum situs",
            category="Pengaturan Sistem"
        )
        messages.success(request, "Pengaturan website berhasil diperbarui!")
        return redirect('admin_settings')

    return render(request, 'store/admin_panel/settings.html', {'setting': setting})


@login_required(login_url='/custom-admin-login/')
def admin_logs(request):
    if request.GET.get('action') == 'export_csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="activity_logs_yellow_mangos.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['ID', 'Pengguna', 'Aksi', 'Kategori', 'Waktu'])
        
        logs = ActivityLog.objects.all().order_by('-created_at')
        for log in logs:
            username = log.user.username if log.user else "System"
            writer.writerow([log.id, username, log.action, log.category, log.created_at])
            
        return response

    logs_list = ActivityLog.objects.all().order_by('-created_at')
    return render(request, 'store/admin_panel/logs.html', {'logs_list': logs_list})
