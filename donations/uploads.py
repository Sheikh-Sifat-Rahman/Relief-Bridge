from uuid import uuid4


def goods_photo_path(instance, filename):
    return f"goods/{uuid4().hex}.jpg"
