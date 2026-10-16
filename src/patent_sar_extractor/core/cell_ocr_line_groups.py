"""One bounded physical-row owner for detected and retained cell text boxes."""


def bounds(part):
    points = part["bbox"]
    return (
        min(p[0] for p in points),
        min(p[1] for p in points),
        max(p[0] for p in points),
        max(p[1] for p in points),
    )


def same_line(a, b):
    left, right = bounds(a), bounds(b)
    overlap = min(left[3], right[3]) - max(left[1], right[1])
    height = min(left[3] - left[1], right[3] - right[1])
    return height > 0 and overlap >= 0.5 * height


def group_text_lines(parts):
    """Keep pairwise row membership; tall bridging boxes have no unique owner."""
    if len(parts) > 32:
        return None
    groups = []
    for part in sorted(parts, key=lambda p: (bounds(p)[1], bounds(p)[0])):
        owners = [g for g in groups if any(same_line(part, old) for old in g)]
        if (
            len(owners) > 1
            or owners
            and not all(same_line(part, old) for old in owners[0])
        ):
            return None
        if owners:
            owners[0].append(part)
        else:
            groups.append([part])
        if len(groups) > 8:
            return None
    return groups
