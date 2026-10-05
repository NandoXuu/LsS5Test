# -*- coding: utf-8 -*-
import heapq
import math


def _expand(rect, margin):
    x1, y1, x2, y2 = rect
    return (x1 - margin, y1 - margin, x2 + margin, y2 + margin)


def _point_in_rect(p, rect):
    x, y = p
    x1, y1, x2, y2 = rect
    return x1 < x < x2 and y1 < y < y2


def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _segments_intersect(p1, p2, p3, p4):
    d1 = _cross(p3, p4, p1)
    d2 = _cross(p3, p4, p2)
    d3 = _cross(p1, p2, p3)
    d4 = _cross(p1, p2, p4)
    return ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
           ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0))


def _segment_intersects_rect(p1, p2, rect):
    x1, y1, x2, y2 = rect
    corners = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    for i in range(4):
        if _segments_intersect(p1, p2, corners[i], corners[(i + 1) % 4]):
            return True
    mid = ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0)
    return _point_in_rect(p1, rect) or _point_in_rect(p2, rect) or _point_in_rect(mid, rect)


def _blocked(p1, p2, rects):
    for r in rects:
        if _segment_intersects_rect(p1, p2, r):
            return True
    return False


def find_path(start, end, obstacles, margin=24.0):
    start = (float(start[0]), float(start[1]))
    end = (float(end[0]), float(end[1]))
    rects = [_expand(r, margin) for r in (obstacles or [])]
    nodes = [start, end]
    for (x1, y1, x2, y2) in rects:
        nodes.extend([(x1, y1), (x2, y1), (x2, y2), (x1, y2)])
    seen = set()
    uniq = []
    for p in nodes:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    nodes = uniq
    n = len(nodes)
    adj = [[] for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if not _blocked(nodes[i], nodes[j], rects):
                d = math.hypot(nodes[i][0] - nodes[j][0], nodes[i][1] - nodes[j][1])
                adj[i].append((j, d))
                adj[j].append((i, d))
    dist = [float("inf")] * n
    prev = [-1] * n
    dist[0] = 0.0
    pq = [(0.0, 0)]
    visited = [False] * n
    while pq:
        d, u = heapq.heappop(pq)
        if visited[u]:
            continue
        visited[u] = True
        if u == 1:
            break
        for v, w in adj[u]:
            nd = d + w
            if nd < dist[v]:
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))
    if dist[1] == float("inf"):
        return [start, end]
    path = []
    cur = 1
    while cur != -1:
        path.append(nodes[cur])
        cur = prev[cur]
    path.reverse()
    return path
