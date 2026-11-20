"""A separate private Modal app with no URL, web function, token or volume."""
import modal

from image_spec import image

app = modal.App("private-computer-use-image-smoke")


@app.function(image=image, cpu=1.5, memory=3072, max_containers=1, timeout=300)
async def verify_image():
    from verify import verify
    return await verify()
