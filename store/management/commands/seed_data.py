from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from store.models import Product, SiteSetting, Announcement, Article, ContactMessage

class Command(BaseCommand):
    help = 'Seeds initial sample data for Yellow Mango\'s'

    def handle(self, *args, **options):
        # 1. SiteSetting
        if not SiteSetting.objects.exists():
            SiteSetting.objects.create(
                site_name="Yellow Mango's",
                tagline="Kesegaran mangga asli pilihan berkualitas tinggi di setiap tegukan dan gigitan.",
                seo_description="Nikmati olahan mangga terbaik di Makassar dari Yellow Mango's.",
                phone_primary="081234567890",
                outlet_name="Makassar Pusat",
                outlet_address="Jl. AP Pettarani No. 45, Makassar, Sulawesi Selatan",
                whatsapp_url="https://wa.me/6281234567890",
            )
            self.stdout.write(self.style.SUCCESS('SiteSetting created.'))

        # 2. Products
        if not Product.objects.exists():
            products_data = [
                {
                    "name": "King Mango Thai Signature",
                    "category": "Smoothies & Jus",
                    "price": 28000,
                    "description": "Smoothies mangga harum manis kental dengan whipped cream lembut, serutan es mangga segar, dan potongan buah mangga melimpah di atasnya.",
                    "badge_primary": "BEST_SELLER",
                    "badge_secondary": "PROMO",
                    "image_url": "/static/images/mangga.jpg",
                },
                {
                    "name": "Mango Sticky Rice Tradisional",
                    "category": "Dessert & Es Krim",
                    "price": 32000,
                    "description": "Ketan gurih pulen disajikan dengan potongan buah mangga matang manis dan saus santan kental khas Thailand yang wangi daun pandan.",
                    "badge_primary": "BEST_SELLER",
                    "badge_secondary": "NEW",
                    "image_url": "/static/images/mango sticky rice.jpg",
                },
                {
                    "name": "Mango Popsicle Real Fruit",
                    "category": "Dessert & Es Krim",
                    "price": 18000,
                    "description": "Es loli beku dari 100% perasan mangga asli segar tanpa pemanis buatan, menyegarkan hari panasmu seketika.",
                    "badge_primary": "PROMO",
                    "badge_secondary": "NONE",
                    "image_url": "/static/images/popsicle mango.jpg",
                },
                {
                    "name": "Creamy Mango Sago Coconut",
                    "category": "Dessert & Es Krim",
                    "price": 30000,
                    "description": "Perpaduan mutiara sagu kenyal, jeli kelapa nata de coco, pure mangga segar, dan kuah santan kelapa creamy menyegarkan.",
                    "badge_primary": "NEW",
                    "badge_secondary": "NONE",
                    "image_url": "/static/images/mangga.jpg",
                },
                {
                    "name": "Pure Mango Cold Pressed Juice",
                    "category": "Smoothies & Jus",
                    "price": 25000,
                    "description": "Jus mangga murni perasan dingin tanpa tambahan air dan gula. Rasa alami manis segar kaya vitamin C.",
                    "badge_primary": "NONE",
                    "badge_secondary": "NONE",
                    "image_url": "/static/images/mangga.jpg",
                },
                {
                    "name": "Mango Coffee Fusion",
                    "category": "Lain-Lain",
                    "price": 26000,
                    "description": "Inovasi unik perpaduan espresso single shot dengan sirup mangga racikan khusus dan susu oat dingin.",
                    "badge_primary": "NEW",
                    "badge_secondary": "NONE",
                    "image_url": "/static/images/mangga.jpg",
                },
            ]
            for p in products_data:
                Product.objects.create(**p)
            self.stdout.write(self.style.SUCCESS(f'{len(products_data)} sample products created.'))

        # 3. Announcement
        if not Announcement.objects.exists():
            Announcement.objects.create(
                title="Promo Spesial Opening & Diskon Midtrans!",
                description="Nikmati kemudahan pembayaran dengan Midtrans (QRIS, GoPay, ShopeePay, Virtual Account) dan dapatkan promo menarik setiap minggunya!",
                announcement_type="PROMO",
                is_active=True,
            )
            self.stdout.write(self.style.SUCCESS('Announcement created.'))

        # 4. Superuser admin if not exists
        if not User.objects.filter(username='admin').exists():
            User.objects.create_superuser('admin', 'admin@yellowmangos.com', 'admin123')
            self.stdout.write(self.style.SUCCESS('Superuser created: username "admin", password "admin123".'))

        self.stdout.write(self.style.SUCCESS('Seed data completed successfully!'))
