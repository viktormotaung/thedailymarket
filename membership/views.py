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
from orders.models import OrderItem
from products.views import download_price_list
from orders.models import Order
from deliveries.models import DeliveryStop


@login_required
def membership_dashboard(request):

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
    # Snapshot
    # ==========================================================

    current_orders = (
        Order.objects
        .filter(client=client)
        .exclude(
            status__in=[
                "DELIVERED",
                "CANCELLED",
            ]
        )
        .count()
    )

    outstanding_amount = (
        Invoice.objects
        .filter(client=client)
        .exclude(status="paid")
        .aggregate(
            total=Sum("order_total_inc")
        )["total"]
        or Decimal("0.00")
    )

    # ==========================================================
    # Recommended Products
    # ==========================================================

    top_products = (
        OrderItem.objects
        .filter(
            order__invoice__client=client,
            order__invoice__status="paid",
        )
        .values("product")
        .annotate(
            total_quantity=Sum("quantity"),
        )
        .order_by("-total_quantity")[:4]
    )

    recommended_products = []

    for item in top_products:

        product = (
            Product.objects
            .select_related("category")
            .filter(id=item["product"])
            .first()
        )

        if product:

            recommended_products.append({
                "product": product,
                "total_quantity": item["total_quantity"],
            })

    # ==========================================================
    # Today's Specials
    # ==========================================================

    special_products = (
        Product.objects
        .filter(is_special=True)
        .select_related("category")
        .order_by("?")[:4]
    )

    # ==========================================================
    # Latest Order
    # ==========================================================

    latest_order = (
        Order.objects
        .filter(client=client)
        .order_by("-submitted_at")
        .first()
    )

    context = {

        "title": "Dashboard",

        "profile": profile,
        "client": client,
        "membership": membership,
        "credit_account": credit_account,

        "current_orders": current_orders,
        "outstanding_amount": outstanding_amount,

        "recommended_products": recommended_products,
        "special_products": special_products,

        "latest_order": latest_order,

    }

    return render(
        request,
        "membership/dashboard.html",
        context,
    )


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
    # Top Products
    # ==========================================================

    top_product_rows = (
        OrderItem.objects
        .filter(
            order__invoice__client=client,
            order__invoice__status="paid",
        )
        .values("product")
        .annotate(
            total_quantity=Sum("quantity"),
        )
        .order_by("-total_quantity")[:4]
    )

    top_products = []

    for row in top_product_rows:

        product = (
            Product.objects
            .select_related("category")
            .filter(id=row["product"])
            .first()
        )

        if product:
            top_products.append({
                "product": product,
                "total_quantity": row["total_quantity"],
            })


    

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
        "top_products": top_products,
    }

    return render(
        request,
        "membership/shop.html",
        context,
    )



@login_required
def membership_download_price_list(request):
    return download_price_list(request)


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
                visible="YES",
            )
            .select_related("category")
            .order_by("name")
        )

    else:

        products = (
            Product.objects
            .filter(
                category=category,
                visible="YES",
            )
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

    profile = (
        CustomerProfile.objects
        .select_related("client", "user")
        .filter(user=request.user)
        .first()
    )

    if not profile:
        messages.error(
            request,
            "No customer profile could be found."
        )
        return redirect("home")

    client = profile.client

    membership = (
        Membership.objects
        .filter(client=client)
        .first()
    )

    orders = (
        Order.objects
        .filter(client=client)
        .select_related("client")
        .order_by("-submitted_at")
    )

    latest_order = orders.first()

    context = {
        "title": "Orders",
        "profile": profile,
        "client": client,
        "membership": membership,
        "orders": orders,
        "latest_order": latest_order,
    }

    return render(
        request,
        "membership/orders.html",
        context,
    )


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
            visible="YES",
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
def membership_view_order(request, order_id):

    profile = (
        CustomerProfile.objects
        .select_related("client", "user")
        .filter(user=request.user)
        .first()
    )

    if not profile:
        messages.error(
            request,
            "No customer profile could be found."
        )
        return redirect("home")

    client = profile.client

    membership = (
        Membership.objects
        .filter(client=client)
        .first()
    )

    order = (
        Order.objects
        .filter(
            id=order_id,
            client=client,
        )
        .first()
    )

    if not order:
        messages.error(
            request,
            "Order could not be found."
        )
        return redirect("membership_orders")

    order_items = (
        OrderItem.objects
        .filter(order=order)
        .select_related(
            "product",
            "product__category",
        )
        .order_by("id")
    )

    delivery_stop = (
        DeliveryStop.objects
        .select_related(
            "run",
            "run__driver",
            "run__vehicle",
        )
        .filter(order=order)
        .first()
    )

    invoice = (
        Invoice.objects
        .filter(order=order)
        .first()
    )

    context = {
        "title": f"Order #{order.id}",
        "profile": profile,
        "client": client,
        "membership": membership,
        "order": order,
        "order_items": order_items,
        "invoice": invoice,
        "delivery_stop": delivery_stop,
    }

    return render(
        request,
        "membership/view_order.html",
        context,
    )


@login_required
def membership_view_invoice(request, invoice_id):

    profile = (
        CustomerProfile.objects
        .select_related("client", "user")
        .filter(user=request.user)
        .first()
    )

    if not profile:
        messages.error(
            request,
            "No customer profile could be found."
        )
        return redirect("home")

    client = profile.client

    membership = (
        Membership.objects
        .filter(client=client)
        .first()
    )

    invoice = (
        Invoice.objects
        .filter(
            id=invoice_id,
            client=client,
        )
        .select_related(
            "order",
            "client",
        )
        .first()
    )

    if not invoice:
        messages.error(
            request,
            "Invoice could not be found."
        )
        return redirect("membership_orders")

    order_items = (
        OrderItem.objects
        .filter(order=invoice.order)
        .select_related(
            "product",
            "product__category",
        )
        .order_by("id")
    )

    order = invoice.order

    order_items = (
        OrderItem.objects
        .filter(order=order)
        .select_related(
            "product",
            "product__category",
        )
        .order_by("id")
    )

    delivery_stop = (
        DeliveryStop.objects
        .select_related(
            "run",
            "run__driver",
        )
        .filter(order=order)
        .first()
    )

    context = {
        "title": f"Invoice INV-{invoice.id:06d}",
        "profile": profile,
        "client": client,
        "membership": membership,
        "invoice": invoice,
        "order": order,
        "order_items": order_items,
        "delivery_stop": delivery_stop,
    }

    

    return render(
        request,
        "membership/view_invoice.html",
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



def membership_delivery_note(request, order_id):

    profile = (
        CustomerProfile.objects
        .select_related("client")
        .filter(user=request.user)
        .first()
    )

    if not profile:
        messages.error(
            request,
            "No customer profile could be found."
        )
        return redirect("home")

    order = (
        Order.objects
        .filter(
            id=order_id,
            client=profile.client,
        )
        .first()
    )

    if not order:
        messages.error(
            request,
            "Order could not be found."
        )
        return redirect("membership_orders")

    delivery_stop = (
        DeliveryStop.objects
        .select_related(
            "run",
            "run__driver",
            "run__vehicle",
        )
        .filter(order=order)
        .first()
    )

    if not delivery_stop:
        messages.warning(
            request,
            "A delivery note has not been created yet."
        )
        return redirect(
            "membership_view_order",
            order_id=order.id,
        )

    context = {
        "title": f"Delivery Note - Order #{order.id}",
        "profile": profile,
        "client": profile.client,
        "order": order,
        "delivery_stop": delivery_stop,
        "items": delivery_stop.items.all(),
    }

    return render(
        request,
        "membership/delivery_note.html",
        context,
    )

