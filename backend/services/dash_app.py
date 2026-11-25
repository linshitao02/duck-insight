# -*- coding: utf-8 -*-
"""Plotly Dash 看板引擎：按 bi_board.layout_json 渲染 FineBI 风格监测看板。"""
from __future__ import annotations

from urllib.parse import parse_qs

from utils.auth import current_user
from utils.db import query as db_query
from utils.field_labels import label_zh_for

DASH_PREFIX = "/bi-dash/"
COLORS = ["#1d6fd8", "#0f766e", "#c2410c", "#7c3aed", "#db2777", "#0891b2", "#ca8a04", "#334155"]


def _parse_bid(pathname, search=None):
    qs = parse_qs((search or "").lstrip("?"))
    for key in ("board", "id", "bid"):
        raw = (qs.get(key) or [None])[0]
        if raw and str(raw).isdigit():
            return int(raw)
    if not pathname:
        return None
    parts = [p for p in str(pathname).split("/") if p]
    if "view" in parts:
        idx = parts.index("view")
        if idx + 1 < len(parts) and parts[idx + 1].isdigit():
            return int(parts[idx + 1])
    if parts and parts[-1].isdigit():
        return int(parts[-1])
    return None


def _token_from(search, request):
    qs = parse_qs((search or "").lstrip("?"))
    token = (qs.get("token") or [None])[0]
    if token:
        return token
    header = request.headers.get("Authorization") or ""
    if header.lower().startswith("bearer "):
        return header.split(" ", 1)[1].strip()
    return request.args.get("token") or request.cookies.get("token") or ""


def _user_by_token(token):
    if not token:
        return None
    return db_query("SELECT * FROM sys_user WHERE token=%s AND status=1", (token,), one=True)


def _kpi_card(title, value, unit, color):
    from dash import html
    text = "—"
    if value is not None:
        try:
            num = float(value)
            text = f"{num:,.2f}" if abs(num) < 1000 else f"{num:,.0f}"
        except (TypeError, ValueError):
            text = str(value)
    return html.Div([
        html.Div(title, className="kpi-label"),
        html.Div([
            html.Span(text, className="kpi-value"),
            html.Span(unit or "", className="kpi-unit"),
        ], className="kpi-row"),
    ], className="kpi-card", style={"borderTopColor": color})


def _axis_title(field):
    return label_zh_for(field) or field


def build_figure(widget, payload):
    import plotly.graph_objects as go

    wtype = widget.get("type") or "line"
    records = payload.get("records") or []
    labels = payload.get("labels") or {}
    dims = payload.get("dim_fields") or []
    meas = payload.get("measure_fields") or []
    height = max(220, int((widget.get("h") or 4) * 72))

    def _label(field):
        if not field:
            return ""
        if field in ("_bucket", "ts"):
            return labels.get(field) or "时间"
        return labels.get(field) or _axis_title(field)

    layout = dict(
        template="plotly_white",
        colorway=COLORS,
        margin=dict(l=48, r=24, t=36, b=42),
        height=height,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        font=dict(family="DM Sans, Microsoft YaHei, sans-serif", size=12, color="#1a2433"),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#f7fafc",
        title=dict(text=widget.get("title") or "", font=dict(size=14, color="#1a2433")),
        hovermode="x unified" if wtype in ("line", "area", "combo") else "closest",
    )
    fig = go.Figure()
    if wtype == "pie":
        dim = dims[0] if dims else None
        mea = meas[0] if meas else None
        if dim and mea:
            fig.add_trace(go.Pie(
                labels=[r.get(dim) for r in records],
                values=[r.get(mea) for r in records],
                hole=0.46,
                textinfo="label+percent",
            ))
            layout["showlegend"] = False
            layout["margin"] = dict(l=16, r=16, t=36, b=16)
    elif wtype == "heatmap" and len(dims) >= 2 and meas:
        x_field, y_field, z_field = dims[0], dims[1], meas[0]
        xs = sorted({r.get(x_field) for r in records if r.get(x_field) is not None}, key=lambda v: str(v))
        ys = list(dict.fromkeys(r.get(y_field) for r in records if r.get(y_field) is not None))
        grid = {(r.get(x_field), r.get(y_field)): r.get(z_field) for r in records}
        z = [[grid.get((x, y)) for x in xs] for y in ys]
        fig.add_trace(go.Heatmap(x=xs, y=ys, z=z, colorscale="Tealgrn", colorbar=dict(thickness=14)))
        layout["xaxis"] = dict(title=_label(x_field))
        layout["yaxis"] = dict(title=_label(y_field), autorange="reversed")
        layout["hovermode"] = "closest"
    elif wtype == "scatter":
        cols = payload.get("columns") or []
        x_field = cols[0] if cols else None
        y_field = cols[1] if len(cols) > 1 else None
        color = widget.get("color_field") if widget.get("color_field") in cols else None
        if x_field and y_field:
            if color:
                groups = {}
                for r in records:
                    groups.setdefault(str(r.get(color) or "其他"), []).append(r)
                for i, (name, rows) in enumerate(groups.items()):
                    fig.add_trace(go.Scatter(
                        x=[r.get(x_field) for r in rows],
                        y=[r.get(y_field) for r in rows],
                        mode="markers",
                        name=name,
                        marker=dict(size=8, opacity=0.7, color=COLORS[i % len(COLORS)]),
                    ))
            else:
                fig.add_trace(go.Scatter(
                    x=[r.get(x_field) for r in records],
                    y=[r.get(y_field) for r in records],
                    mode="markers",
                    marker=dict(size=8, opacity=0.65, color=COLORS[0]),
                    name=_axis_title(y_field),
                ))
            layout["xaxis"] = dict(title=_label(x_field))
            layout["yaxis"] = dict(title=_label(y_field))
    else:
        x_field = dims[0] if dims else None
        x = [r.get(x_field) for r in records] if x_field else list(range(len(records)))
        secondary = set(widget.get("secondary") or [])
        for i, alias in enumerate(meas):
            raw = alias.split("__")[0]
            y = [r.get(alias) for r in records]
            name = labels.get(alias) or _axis_title(raw)
            axis = "y2" if (wtype == "combo" and (raw in secondary or i == len(meas) - 1 and len(meas) > 1)) else "y"
            if wtype == "bar":
                fig.add_trace(go.Bar(x=x, y=y, name=name, marker_color=COLORS[i % len(COLORS)]))
            elif wtype == "hbar":
                fig.add_trace(go.Bar(x=y, y=x, name=name, orientation="h", marker_color=COLORS[i % len(COLORS)]))
            elif wtype == "area":
                fig.add_trace(go.Scatter(x=x, y=y, name=name, fill="tozeroy", mode="lines",
                                         line=dict(color=COLORS[i % len(COLORS)], width=2)))
            elif wtype == "combo" and axis == "y":
                fig.add_trace(go.Bar(x=x, y=y, name=name, marker_color=COLORS[i % len(COLORS)], opacity=0.85))
            else:
                fig.add_trace(go.Scatter(
                    x=x, y=y, name=name, mode="lines",
                    line=dict(color=COLORS[i % len(COLORS)], width=2.2),
                    yaxis=axis,
                ))
        if wtype == "hbar":
            layout["xaxis"] = dict(title="")
            layout["yaxis"] = dict(title=_label(x_field) if x_field else "")
        else:
            layout["xaxis"] = dict(title=_label(x_field) if x_field else "")
            layout["yaxis"] = dict(title="", gridcolor="#e2e8f0", zeroline=False)
            if wtype == "combo":
                layout["yaxis2"] = dict(overlaying="y", side="right", title="", showgrid=False)
                layout["barmode"] = "group"
            if wtype == "bar":
                layout["barmode"] = "group"
    fig.update_layout(**layout)
    return fig


INDEX_CSS = """
.dash-board { font-family: "DM Sans","Microsoft YaHei",sans-serif; background:#e8eef5; min-height:100vh; color:#1a2433; }
.dash-top { display:flex; justify-content:space-between; align-items:flex-end; gap:16px; padding:16px 22px 12px; background:#fff; border-bottom:1px solid #d5dee8; }
.dash-top h1 { font-size:18px; margin:0 0 4px; }
.dash-top p { margin:0; color:#64748b; font-size:12px; }
.dash-filters { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
.dash-grid { display:grid; grid-template-columns:repeat(12,1fr); grid-auto-rows:72px; gap:10px; padding:14px 16px 28px; }
.dash-cell { background:#fff; border:1px solid #d5dee8; border-radius:12px; overflow:hidden; box-shadow:0 1px 2px rgba(26,36,51,.04); }
.dash-table-wrap { padding:10px 12px; overflow:auto; height:100%; }
.kpi-card { height:100%; padding:16px 18px; border-top:3px solid #1d6fd8; }
.kpi-label { color:#64748b; font-size:12px; font-weight:600; }
.kpi-row { display:flex; align-items:baseline; gap:8px; margin-top:10px; }
.kpi-value { font-size:22px; font-weight:700; letter-spacing:-0.03em; line-height:1.2; }
.kpi-unit { color:#64748b; font-size:12px; }
.dash-empty { padding:48px; text-align:center; color:#64748b; }
.refresh-tip { color:#64748b; font-size:12px; }
.Select-control, .dash-dropdown { min-width:160px; }
"""


def attach_dash(flask_app):
    try:
        from dash import Dash, Input, Output, dcc, html, dash_table
    except Exception as e:
        print(f"[BI] 未安装 dash/plotly，跳过看板引擎: {e}")
        return None

    dash_app = Dash(
        __name__,
        server=flask_app,
        url_base_pathname=DASH_PREFIX,
        suppress_callback_exceptions=True,
        title="Duck Insight BI",
    )
    dash_app.index_string = """<!DOCTYPE html>
<html>
<head>
{%metas%}
<title>{%title%}</title>
{%favicon%}
{%css%}
<style>""" + INDEX_CSS + """</style>
</head>
<body>
{%app_entry%}
<footer>{%config%}{%scripts%}{%renderer%}</footer>
</body>
</html>"""

    dash_app.layout = html.Div([
        dcc.Location(id="url"),
        dcc.Store(id="board-meta"),
        dcc.Interval(id="auto-refresh", interval=60000),
        html.Div([
            html.Div([
                html.H1(id="board-title", children="BI 看板"),
                html.P(id="board-desc", children="Plotly Dash · 自助分析看板"),
            ]),
            html.Div([
                dcc.Dropdown(id="flt-site", options=[{"label": "全部站点", "value": ""}], value="",
                             clearable=False, className="dash-dropdown", style={"width": "180px"}),
                html.Span(id="refresh-tip", className="refresh-tip", children="每 60 秒自动刷新"),
            ], className="dash-filters"),
        ], className="dash-top"),
        html.Div(id="grid"),
    ], className="dash-board")

    @dash_app.callback(
        Output("board-title", "children"),
        Output("board-desc", "children"),
        Output("flt-site", "options"),
        Output("flt-site", "style"),
        Output("board-meta", "data"),
        Input("url", "pathname"),
        Input("url", "search"),
    )
    def render_page(pathname, search):
        from flask import request
        from services import bi_service

        bid = _parse_bid(pathname, search)
        token = _token_from(search, request)
        user = _user_by_token(token) or current_user()
        empty_opts = [{"label": "全部", "value": ""}]
        hidden = {"display": "none"}
        shown = {"width": "180px"}
        if not user:
            return "未登录", "请从 Duck Insight 登录后打开看板。", empty_opts, hidden, None
        if not bid:
            return "BI 看板", "未指定看板。", empty_opts, hidden, None
        board = bi_service.get_board(bid)
        if not board:
            return "看板不存在", "看板不存在或已删除。", empty_opts, hidden, None
        layout = board.get("layout") or {}
        info = None
        src = layout.get("default_source") or {}
        if src.get("id"):
            try:
                info = bi_service.describe_source(src.get("kind") or "dataset", src["id"])
            except Exception:
                info = None
        site_opts = list(empty_opts)
        if info:
            for flt in info.get("filters") or []:
                if flt.get("field") in ("site_name", "site"):
                    site_opts += [{"label": v, "value": v} for v in flt.get("values") or []]
                    break
        grain = layout.get("grain") or board.get("grain") or "day"
        meta = {
            "id": bid, "token": token, "grain": grain,
            "realtime": bool(layout.get("realtime")),
        }
        desc = board.get("description") or "Plotly Dash · 自助分析看板"
        if meta["realtime"]:
            desc = f"{desc} · 实时读取，每 60 秒自动刷新"
        site_style = shown if len(site_opts) > 1 else hidden
        return board.get("name") or "BI 看板", desc, site_opts, site_style, meta

    @dash_app.callback(
        Output("grid", "children"),
        Input("board-meta", "data"),
        Input("flt-site", "value"),
        Input("auto-refresh", "n_intervals"),
        prevent_initial_call=False,
    )
    def render_grid(meta, site, _tick):
        from dash import html
        from services import bi_service

        if not meta or not meta.get("id"):
            return html.Div("请从 Duck Insight 登录后打开看板。", className="dash-empty")
        filters = []
        if site:
            filters.append({"field": "site_name", "type": "select", "value": [site]})
        packed = bi_service.query_board_layout(meta["id"], grain=meta.get("grain"), filters=filters)
        cells = []
        for i, item in enumerate(packed.get("items") or []):
            w = item.get("widget") or {}
            data = item.get("data") or {}
            x = int(w.get("x") or 0) + 1
            y = int(w.get("y") or 0) + 1
            ww = int(w.get("w") or 4)
            hh = int(w.get("h") or 3)
            style = {
                "gridColumn": f"{x} / span {ww}",
                "gridRow": f"{y} / span {hh}",
            }
            wtype = w.get("type") or "line"
            if wtype == "kpi":
                kpi = (data.get("kpis") or [{}])[0]
                color = COLORS[i % len(COLORS)]
                child = _kpi_card(w.get("title") or kpi.get("label"), kpi.get("value"), w.get("unit"), color)
            elif wtype == "table":
                cols = [{"name": (data.get("labels") or {}).get(c) or _axis_title(c), "id": c} for c in (data.get("columns") or [])]
                child = html.Div(dash_table.DataTable(
                    columns=cols,
                    data=data.get("records") or [],
                    page_size=8,
                    style_table={"overflowX": "auto"},
                    style_cell={"fontFamily": "DM Sans, Microsoft YaHei", "fontSize": "12px", "padding": "6px 8px"},
                    style_header={"background": "#f7fafc", "fontWeight": "600", "color": "#64748b"},
                ), className="dash-table-wrap")
            else:
                fig = build_figure(w, data)
                child = dcc.Graph(figure=fig, config={"displaylogo": False, "responsive": True}, style={"height": "100%"})
            cells.append(html.Div(child, className="dash-cell", style=style))
        if not cells:
            return html.Div("看板还没有组件，请在设计器中拖入图表。", className="dash-empty")
        return html.Div(cells, className="dash-grid")

    print("[BI] Plotly Dash 已挂载 /bi-dash/")
    return dash_app
