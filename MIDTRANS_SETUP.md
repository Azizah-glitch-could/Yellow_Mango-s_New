# Panduan Alur Aplikasi & Integrasi Midtrans Snap - Yellow Mango's

Project ini telah dikonfigurasi agar alur pemesanan dari awal buka website hingga pembayaran Midtrans berjalan lancar dan tanpa error.

---

## 🥭 Alur Pemesanan & Pembayaran Lengkap

1. **Buka Website (`/`)**:
   - Menampilkan promo aktif, produk unggulan (*Best Seller*), kategori menu, artikel, dan ulasan pelanggan.
   - Pelanggan dapat menjelajahi menu lewat navigasi atau halaman katalog menu (`/menu/`).

2. **Pilih Menu & Atur Kustomisasi (`/menu/produk/<id>/`)**:
   - Pelanggan memilih variasi ukuran (Reguler / Large), tingkat kemanisan (level gula), level es, catatan dapur, serta kuantitas.
   - Klik **"Tambah ke Keranjang"** atau **"Beli Sekarang"**.

3. **Keranjang Belanja (`/cart/`)**:
   - Menampilkan daftar sajian, rincian variasi, kuantitas (bisa ditambah/dikurang/dihapus), dan ringkasan total pembayaran.
   - Tombol **"Lanjut ke Checkout"**:
     - **Jika sudah login**: Langsung menuju halaman `/checkout/`.
     - **Jika belum memiliki akun / belum login**: Otomatis dialihkan ke halaman Login & Pendaftaran (`/login/?next=/checkout/`) dengan membawa pesan informatif, dan keranjang belanja tetap tersimpan aman.

4. **Login / Pendaftaran Akun (`/login/`)**:
   - Pengunjung yang belum punya akun dapat mengklik tab **Daftar** (*Sign Up*) untuk membuat akun baru dengan nama, nomor WhatsApp aktif, username/email, dan password.
   - Setelah berhasil mendaftar atau berhasil login, pengguna **langsung dialihkan kembali ke halaman checkout** (`/checkout/`).
   - Data nama dan nomor WhatsApp otomatis terisi (*pre-filled*) ke form checkout.

5. **Form Checkout & Pemesanan (`/checkout/`)**:
   - Menampilkan data pemesan, pilihan tipe layanan (*Pesan Antar / Delivery*, *Ambil di Toko / Takeaway*, *Makan di Tempat / Dine-in*), alamat pengiriman, dan catatan pesanan.
   - Klik **"Lanjutkan ke Pembayaran"**:
     - Sistem membuat data `Order` (status: `PENDING`, pembayaran: `UNPAID`) dan data item pesanan.
     - Keranjang belanja dikosongkan.
     - Pengguna dialihkan ke halaman pembayaran: `/pembayaran/<order_number>/`.

6. **Halaman Pembayaran Midtrans (`/pembayaran/<order_number>/`)**:
   - Menampilkan rincian pesanan dan total harga.
   - Menampilkan tombol **"Bayar Sekarang dengan Midtrans"** yang memunculkan popup resmi **Midtrans Snap** (QRIS, GoPay, ShopeePay, Virtual Account Bank BCA/BNI/BRI/Mandiri, Kartu Kredit).
   - *Mode Pengujian (DEBUG)*: Tersedia tombol **"🧪 Simulasi Pembayaran Berhasil"** sehingga alur dapat diuji langsung meskipun API Key Sandbox Midtrans belum diisi.

7. **Status Pembayaran & Order Success (`/order-success/<order_number>/`)**:
   - **Midtrans Webhook (`/midtrans/notification/`)**: Midtrans mengirim notifikasi pembayaran dan sistem memverifikasi signature SHA-512 lalu mengubah status pembayaran menjadi `PAID` dan pesanan menjadi `PROCESSING`.
   - **Auto Check API**: Saat halaman sukses dibuka, sistem juga otomatis memverifikasi status transaksi langsung ke API Midtrans sehingga status langsung terupdate menjadi `PAID` meskipun diuji di `localhost` tanpa webhook internet/ngrok.
   - Terdapat tombol **"Konfirmasi Pesanan ke WhatsApp Toko"** dengan pesan otomatis berisi nomor pesanan dan total harga.

---

## 🚀 Cara Menjalankan Project

### 1. File Konfigurasi `.env`
File `.env` sudah disediakan di folder utama project:
```env
DJANGO_SECRET_KEY=django-insecure-yellow-mangos-secret-key-development-2026
DEBUG=True

# Database: 'sqlite' (otomatis tanpa XAMPP) atau 'mysql' (jika XAMPP menyala)
DB_ENGINE=sqlite

# Kredensial Midtrans Sandbox
MIDTRANS_SERVER_KEY=SB-Mid-server-GANTI_DENGAN_SERVER_KEY_SANDBOX_KAMU
MIDTRANS_CLIENT_KEY=SB-Mid-client-GANTI_DENGAN_CLIENT_KEY_SANDBOX_KAMU
MIDTRANS_SIGNATURE_KEY=GANTI_DENGAN_SIGNATURE_KEY_SANDBOX_KAMU
MIDTRANS_IS_PRODUCTION=False
MIDTRANS_FINISH_URL=http://127.0.0.1:8000/
```

### 2. Jalankan Server
Gunakan virtual environment `venv` yang sudah terpasang:
```powershell
.\venv\Scripts\python.exe manage.py runserver
```
Buka browser di: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)

### 3. Akun Administrator Bawaan
- **URL Admin**: [http://127.0.0.1:8000/custom-admin-login/](http://127.0.0.1:8000/custom-admin-login/) atau [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/)
- **Username**: `admin`
- **Password**: `admin123`
