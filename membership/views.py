from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from clients.models import Membership, Client
from django.contrib import messages

from profiles.models import CustomerProfile

@login_required
def membership_dashboard(request):
    return render(request, "membership/dashboard.html")


@login_required
def membership_shop(request):
    return render(request, "membership/shop.html")


@login_required
def membership_orders(request):
    return render(request, "membership/orders.html")


@login_required
def membership_membership(request):
    return render(request, "membership/membership.html")







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