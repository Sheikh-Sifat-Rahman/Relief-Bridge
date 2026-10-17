from django.shortcuts import get_object_or_404, redirect, render

from accounts.permissions import active_role_required
from distributions.models import Distribution

from .forms import AidRequestForm
from .models import AidRequest


@active_role_required("AID_SEEKER")
def home(request):
    return render(
        request,
        "seeker/home.html",
        {
            "section": request.resolver_match.url_name,
            "page_title": {
                "requests": "My aid requests",
                "received": "Aid received",
                "history": "Distribution history",
            }.get(request.resolver_match.url_name, "Aid seeker dashboard"),
            "requests": AidRequest.objects.filter(
                seeker__user=request.user
            ).select_related("campaign"),
            "distributions": Distribution.objects.filter(
                beneficiary__user=request.user,
                **(
                    {"status": "COMPLETED"}
                    if request.resolver_match.url_name == "received"
                    else {}
                ),
            )
            .select_related("distribution_event")
            .prefetch_related("items__inventory_item"),
        },
    )


@active_role_required("AID_SEEKER")
def profile(request):
    return redirect("accounts:household")


@active_role_required("AID_SEEKER")
def create(request):
    form = AidRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.seeker = request.user.seeker_profile
        obj.save()
        return redirect("seeker:detail", pk=obj.pk)
    return render(
        request,
        "form.html",
        {
            "form": form,
            "title": "Request assistance",
            "note": "Priority is advisory. A human coordinator reviews every request.",
        },
    )


@active_role_required("AID_SEEKER")
def detail(request, pk):
    obj = get_object_or_404(AidRequest, pk=pk, seeker__user=request.user)
    return render(request, "seeker/detail.html", {"aid_request": obj})
