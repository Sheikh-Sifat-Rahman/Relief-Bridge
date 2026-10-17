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
    from distributions.models import DistributionAllocation
    from inventory.models import InventoryBatch

    batches = list(
        InventoryBatch.objects.filter(donation_item__donation=donation).select_related(
            "donation_item", "inventory_item__warehouse"
        )
    )
    timeline = [
        {
            "date": donation.created_at,
            "title": "Pledge submitted",
            "detail": donation.donation_code,
        }
    ]
    if donation.reviewed_at:
        timeline.append(
            {
                "date": donation.reviewed_at,
                "title": f"Admin review: {donation.get_review_status_display()}",
                "detail": donation.review_reason,
            }
        )
    for item in donation.items.all():
        if item.inspected_at:
            timeline.append(
                {
                    "date": item.inspected_at,
                    "title": "Inspection completed",
                    "detail": f"{item.item_name}: {item.accepted_quantity} {item.unit} accepted, {item.rejected_quantity} rejected. {item.rejection_reason}",
                }
            )
    for batch in batches:
        delivered = (
            batch.allocations.filter(status="DELIVERED").aggregate(
                total=Sum("quantity")
            )["total"]
            or 0
        )
        batch.delivered_quantity = delivered
        batch.other_out_quantity = (
            batch.received_quantity - batch.remaining_quantity - delivered
        )
        batch.available_quantity = batch.remaining_quantity - batch.reserved_quantity
        timeline.append(
            {
                "date": batch.received_at,
                "title": "Received into warehouse",
                "detail": f"{batch.received_quantity} {batch.inventory_item.unit} {batch.inventory_item.item_name} · {batch.inventory_item.warehouse.name}",
            }
        )
    for allocation in DistributionAllocation.objects.filter(
        batch__in=batches
    ).select_related("batch__inventory_item"):
        description = f"{allocation.quantity} {allocation.batch.inventory_item.unit} {allocation.batch.inventory_item.item_name}"
        timeline.append(
            {
                "date": allocation.created_at,
                "title": "Reserved for delivery",
                "detail": description,
            }
        )
        if allocation.status != "RESERVED":
            timeline.append(
                {
                    "date": allocation.updated_at,
                    "title": "Delivered"
                    if allocation.status == "DELIVERED"
                    else "Reservation released",
                    "detail": description,
                }
            )
    timeline.sort(key=lambda entry: entry["date"])
    return render(
        request,
        "donor/detail.html",
        {"donation": donation, "batches": batches, "timeline": timeline},
    )


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
