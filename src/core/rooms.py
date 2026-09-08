"""Ruimtedetectie (vloeivulling/flood-fill op de schone lijntekening)."""

import numpy as np
from PIL import Image


def detect_room_boxes(
    clean_img: Image.Image, dilate_iters: int = 4, min_pixels: int = 25000
) -> tuple[dict[int, tuple[int, int, int, int]], np.ndarray]:
    """Vind ruimtes als omsloten witte gebieden in de schone lijntekening.

    Retourneert (boxes, labels): boxes is {label_id: (x0,y0,x1,y1)} in
    pixelcoordinaten, labels is de scipy-ndimage-labelmatrix (nodig voor
    naam-matching in names.py).
    """
    from scipy import ndimage

    arr = np.array(clean_img)
    wall_mask = arr[..., 3] > 80
    struct = ndimage.generate_binary_structure(2, 2)
    dilated = ndimage.binary_dilation(wall_mask, structure=struct, iterations=dilate_iters)
    bg = ~dilated
    labels, num = ndimage.label(bg, structure=np.ones((3, 3)))
    if num == 0:
        return {}, labels
    sizes = ndimage.sum(bg, labels, range(1, num + 1))
    order = np.argsort(sizes)[::-1]
    exterior_label = int(order[0]) + 1  # grootste component = buitenwereld
    room_ids = [
        int(i) + 1 for i in order if sizes[i] > min_pixels and int(i) + 1 != exterior_label
    ]

    objs = ndimage.find_objects(labels)
    boxes = {}
    for lid in room_ids:
        sl = objs[lid - 1]
        y0, y1 = sl[0].start, sl[0].stop
        x0, x1 = sl[1].start, sl[1].stop
        boxes[lid] = (x0, y0, x1, y1)
    return boxes, labels
