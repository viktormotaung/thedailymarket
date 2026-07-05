from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from clients.models import Membership, Client
from django.contrib import messages
from credit.models import CreditAccount
from profiles.models import CustomerProfile
from datetime import date
from decimal import Decimal
from products.models import Category, Product
from django.db.models import Sum, Count, Q
from invoices.models import Invoice

@login_required
def membership_dashboard(request):
    return render(request, "membership/dashboard.html")


@login_required
def membership_shop(request):

    profile = (
        CustomerProfile.objects
        .select_related("client", "user")
        .filter(user=request.user)
        .first()
    )

    if not profile:
        messages.error(
            request,
            "No customer profile could be found for your account."
        )
        return redirect("home")

    client = profile.client

    membership = (
        Membership.objects
        .filter(client=client)
        .first()
    )

    credit_account = (
        CreditAccount.objects
        .filter(client=client)
        .first()
    )

    # ==========================================================
    # This Month Statistics
    # ==========================================================

    today = date.today()

    invoices = (
        Invoice.objects
        .filter(
            client=client,
            status="paid",
            paid_date__year=today.year,
            paid_date__month=today.month,
        )
    )

    monthly_spend = (
        invoices.aggregate(
            total=Sum("order_total_inc")
        )["total"]
        or Decimal("0.00")
    )

    monthly_paid_invoices = invoices.count()

    average_basket = (
        monthly_spend / monthly_paid_invoices
        if monthly_paid_invoices
        else Decimal("0.00")
    )

    # ==========================================================
    # Shop Categories
    # ==========================================================

    categories = (
        Category.objects
        .filter(
            parent__isnull=True,
            is_active=True,
        )
        .prefetch_related(
            "children__products",
            "products",
        )
        .order_by("sort_order", "name")
    )

    category_cards = []

    for category in categories:

        child_categories = category.children.all()

        if child_categories.exists():

            product_count = Product.objects.filter(
                category__in=child_categories
            ).count()

        else:

            product_count = category.products.count()

        category_cards.append({
            "category": category,
            "display_name": (
                category.name
                .replace("_", " ")
                .replace("&", " & ")
                .title()
            ),
            "product_count": product_count,
        })

    context = {
        "title": "Shop",
        "profile": profile,
        "client": client,
        "membership": membership,
        "credit_account": credit_account,
        "monthly_spend": monthly_spend,
        "monthly_paid_invoices": monthly_paid_invoices,
        "average_basket": average_basket,
        "user": request.user,
        "category_cards": category_cards,
    }

    return render(
        request,
        "membership/shop.html",
        context,
    )





@login_required
def membership_shop_category(request, slug):

    profile = (
        CustomerProfile.objects
        .select_related("client", "user")
        .filter(user=request.user)
        .first()
    )

    if not profile:
        messages.error(
            request,
            "No customer profile could be found for your account."
        )
        return redirect("home")

    client = profile.client

    membership = (
        Membership.objects
        .filter(client=client)
        .first()
    )

    credit_account = (
        CreditAccount.objects
        .filter(client=client)
        .first()
    )

    category = (
        Category.objects
        .filter(
            slug=slug,
            is_active=True,
        )
        .first()
    )

    if not category:
        messages.error(
            request,
            "Category could not be found."
        )
        return redirect("membership_shop")

    child_categories = (
        category.children
        .filter(is_active=True)
        .order_by("sort_order", "name")
    )

    if child_categories.exists():

        products = (
            Product.objects
            .filter(
                category__in=child_categories,
            )
            .select_related("category")
            .order_by("name")
        )

    else:

        products = (
            Product.objects
            .filter(category=category)
            .select_related("category")
            .order_by("name")
        )

    category_display_name = (
        category.name
        .replace("_", " ")
        .replace("&", " & ")
        .title()
    )

    search = request.GET.get("search", "").strip()

    if search:
        products = products.filter(
            Q(name__icontains=search) |
            Q(category__name__icontains=search) |
            Q(category__parent__name__icontains=search)
        ).distinct()

    context = {
        "title": category.name,
        "profile": profile,
        "client": client,
        "membership": membership,
        "credit_account": credit_account,
        "category": category,
        "child_categories": child_categories,
        "products": products,
        "category_display_name": category_display_name,
        "search": search,
    }

    return render(
        request,
        "membership/shop_category.html",
        context,
    )


@login_required
def membership_orders(request):
    return render(request, "membership/orders.html")


@login_required
def membership_membership(request):
    return render(request, "membership/membership.html")


@login_required
def membership_shop_specials(request):

    profile = (
        CustomerProfile.objects
        .select_related("client", "user")
        .filter(user=request.user)
        .first()
    )

    if not profile:
        messages.error(
            request,
            "No customer profile could be found for your account."
        )
        return redirect("home")

    client = profile.client

    membership = (
        Membership.objects
        .filter(client=client)
        .first()
    )

    credit_account = (
        CreditAccount.objects
        .filter(client=client)
        .first()
    )

    products = (
        Product.objects
        .filter(
            is_special=True,
        )
        .select_related("category")
        .order_by("name")
    )

    context = {
        "title": "Shop Specials",
        "profile": profile,
        "client": client,
        "membership": membership,
        "credit_account": credit_account,
        "products": products,
    }

    return render(
        request,
        "membership/shop_specials.html",
        context,
    )





@login_required
def membership_account(request):

    profile = (
        CustomerProfile.objects
        .select_related("client", "user")
        .filter(user=request.user)
        .first()
    )

    if not profile:
        messages.error(
            request,
            "No customer profile could be found for your account."
        )
        return redirect("home")

    client = profile.client

    membership = (
        Membership.objects
        .filter(client=client)
        .first()
    )

    context = {
        "title": "My Account",
        "profile": profile,
        "client": client,
        "membership": membership,
        "user": request.user,
    }

    return render(
        request,
        "membership/account.html",
        context,
    )



@login_required
def membership_support(request):
    return render(request, "membership/support.html")