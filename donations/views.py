from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render

from accounts.forms import DonorProfileForm
from accounts.permissions import active_role_required
from dashboard.views import edit_profile

from .forms import GoodsDonationForm, MoneyDonationForm
from .models import Donation, DonationItem, MoneyDonation
from .services import simulate_payment


@active_role_required("DONOR")
def home(request):
    donations = Donation.objects.filter(donor__user=request.user).select_related(
        "campaign"
    )
    categories = list(
        donations.filter(donation_type="GOODS")
        .values("items__category")
        .annotate(total=Sum("items__quantity"))
    )
    return render(
        request,
        "donor/home.html",
        {
            "section": request.resolver_match.url_name,
            "page_title": {
                "donations": "My donations",
                "history": "Donation history",
            }.get(request.resolver_match.url_name, "Donor dashboard"),
            "donations": donations,
            "donation_count": donations.count(),
            "money_total": MoneyDonation.objects.filter(
                donation__in=donations, payment_status="SUCCESS"
            ).aggregate(v=Sum("amount"))["v"]
            or 0,
            "goods_total": DonationItem.objects.filter(
                donation__in=donations
            ).aggregate(v=Sum("quantity"))["v"]
            or 0,
            "chart_labels": [x["items__category"] for x in categories],
            "chart_values": [float(x["total"] or 0) for x in categories],
        },
    )


@active_role_required("DONOR")
def detail(request, pk):
    donation = get_object_or_404(
        Donation.objects.select_related("campaign"), pk=pk, donor__user=request.user
    )
    return render(request, "donor/detail.html", {"donation": donation})


@active_role_required("DONOR")
def profile(request):
    return edit_profile(request, DonorProfileForm, request.user.donor_profile)


@active_role_required("DONOR")
def goods(request):
    form = GoodsDonationForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            donation = Donation.objects.create(
                donor=request.user.donor_profile,
                campaign=form.cleaned_data["campaign"],
                donation_type="GOODS",
            )
            item = form.save(commit=False)
            item.donation = donation
            item.save()
        return redirect("donor:detail", pk=donation.pk)
    return render(
        request,
        "form.html",
        {
            "form": form,
            "title": "Donate useful goods",
            "note": "Your goods pledge requires admin acceptance before inspection and receipt. Please donate clean, usable goods. Medicine donations are outside this prototype.",
        },
    )


@active_role_required("DONOR")
def money(request):
    form = MoneyDonationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        donation = simulate_payment(
            request.user.donor_profile,
            form.cleaned_data["campaign"],
            form.cleaned_data["amount"],
        )
        return redirect("donor:detail", pk=donation.pk)
    return render(
        request,
        "form.html",
        {
            "form": form,
            "title": "Simulate a money donation",
            "note": "SIMULATION ONLY. Your contribution remains pending until admin acceptance. No money is transferred. Never enter banking details or payment secrets.",
        },
    )


@login_required
def photo(request, pk):
    items = DonationItem.objects.all()
    if not request.user.is_staff:
        items = items.filter(donation__donor__user=request.user)
    item = get_object_or_404(items, pk=pk)
    if not item.photo:
        raise Http404("No photo was attached.")
    try:
        response = FileResponse(item.photo.open("rb"), content_type="image/jpeg")
    except FileNotFoundError:
        raise Http404("Photo not found.")
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
