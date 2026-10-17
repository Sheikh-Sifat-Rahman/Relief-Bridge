def notification_count(request):
    return {
        "unread_notification_count": request.user.notifications.filter(
            read_at__isnull=True
        ).count()
        if request.user.is_authenticated
        else 0
    }
