"""
Excel Report Generator — InvestAI
Genera un report Excel professionale con 4 fogli.
"""
from __future__ import annotations

from io import BytesIO
from datetime import date

import pandas as pd


def generate_excel_report(
    df_hist: pd.DataFrame,
    current_portfolio: dict,
    transactions: list[dict] | None = None,
) -> bytes:
    """
    Genera un file Excel con:
    1. Dati Storici
    2. Portafoglio Attuale
    3. Dashboard Grafici
    4. Transazioni

    Parameters
    ----------
    df_hist           : DataFrame storico (output di get_historical_portfolio_value)
    current_portfolio : { ticker: { qty, avg_price, cur_price, pnl_pct, ... } }
    transactions      : lista transazioni raw

    Returns
    -------
    bytes del file .xlsx
    """
    output = BytesIO()

    # Pre-calcoli
    if "Total Invested" not in df_hist.columns:
        df_hist["Total Invested"] = 0.0
    df_hist["Utile Netto (€)"] = df_hist["Total Value"] - df_hist["Total Invested"]
    df_hist["Performance %"]   = df_hist["Total Value"].pct_change().fillna(0)

    cols_main   = ["Total Value", "Total Invested", "Utile Netto (€)", "Performance %"]
    cols_assets = [c for c in df_hist.columns if c not in cols_main]
    df_out      = df_hist[cols_main + cols_assets]

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        wb = writer.book

        # Formati
        fmt_currency  = wb.add_format({"num_format": "€ #,##0.00"})
        fmt_pct       = wb.add_format({"num_format": "0.00%"})
        fmt_green     = wb.add_format({"bg_color": "#C6EFCE", "font_color": "#006100", "num_format": "0.00%"})
        fmt_red       = wb.add_format({"bg_color": "#FFC7CE", "font_color": "#9C0006", "num_format": "0.00%"})
        fmt_cur_green = wb.add_format({"bg_color": "#C6EFCE", "font_color": "#006100", "num_format": "€ #,##0.00"})
        fmt_cur_red   = wb.add_format({"bg_color": "#FFC7CE", "font_color": "#9C0006", "num_format": "€ #,##0.00"})
        fmt_txt_green = wb.add_format({"bg_color": "#C6EFCE", "font_color": "#006100", "bold": True})
        fmt_txt_red   = wb.add_format({"bg_color": "#FFC7CE", "font_color": "#9C0006", "bold": True})

        # ========================
        # FOGLIO 1: DATI STORICI
        # ========================
        sh = "Dati Storici"
        df_out.to_excel(writer, sheet_name=sh, index=True)
        ws = writer.sheets[sh]
        last_row = len(df_out) + 1
        ws.set_column(0, 0, 15)
        ws.set_column(1, 3, 20, fmt_currency)
        ws.set_column(4, 4, 15, fmt_pct)
        ws.set_column(5, len(df_out.columns), 15, fmt_currency)
        if last_row > 1:
            ws.conditional_format(1, 4, last_row, 4, {"type": "cell", "criteria": ">", "value": 0, "format": fmt_green})
            ws.conditional_format(1, 4, last_row, 4, {"type": "cell", "criteria": "<", "value": 0, "format": fmt_red})
            ws.conditional_format(1, 3, last_row, 3, {"type": "cell", "criteria": ">", "value": 0, "format": fmt_cur_green})
            ws.conditional_format(1, 3, last_row, 3, {"type": "cell", "criteria": "<", "value": 0, "format": fmt_cur_red})

        # =============================
        # FOGLIO 2: PORTAFOGLIO ATTUALE
        # =============================
        sh_pf = "Portafoglio"
        rows_pf = []
        for sym, v in current_portfolio.items():
            price = v.get("cur_price", v.get("avg_price", 0.0))
            qty   = v.get("qty", 0.0)
            rows_pf.append({
                "Asset":          sym,
                "Quantità":       qty,
                "Prezzo Medio":   v.get("avg_price", 0.0),
                "Prezzo Attuale": price,
                "Valore Totale":  qty * price,
                "P&L %":         v.get("pnl_pct", 0.0) / 100,
            })
        if rows_pf:
            df_pf = pd.DataFrame(rows_pf)
            df_pf.to_excel(writer, sheet_name=sh_pf, index=False)
            ws_pf = writer.sheets[sh_pf]
            ws_pf.set_column("A:A", 15)
            ws_pf.set_column("B:B", 12)
            ws_pf.set_column("C:E", 18, fmt_currency)
            ws_pf.set_column("F:F", 12, fmt_pct)
            ws_pf.conditional_format(1, 5, len(df_pf), 5, {"type": "cell", "criteria": ">", "value": 0, "format": fmt_green})
            ws_pf.conditional_format(1, 5, len(df_pf), 5, {"type": "cell", "criteria": "<", "value": 0, "format": fmt_red})

        # ==========================
        # FOGLIO 3: DASHBOARD GRAFICI
        # ==========================
        sh_d = "Dashboard Grafici"
        ws_d = wb.add_worksheet(sh_d)
        ws_d.hide_gridlines(2)
        fmt_title = wb.add_format({"bold": True, "font_size": 18, "font_color": "#004d40"})
        ws_d.write("B2", f"Report InvestAI — {date.today().strftime('%d/%m/%Y')}", fmt_title)

        if last_row > 1:
            chart_evo = wb.add_chart({"type": "line"})
            chart_evo.add_series({
                "name":       "Valore Portafoglio",
                "categories": f"='{sh}'!$A$2:$A${last_row}",
                "values":     f"='{sh}'!$B$2:$B${last_row}",
                "line":       {"color": "#004d40", "width": 2.5},
            })
            chart_evo.add_series({
                "name":       "Capitale Investito",
                "categories": f"='{sh}'!$A$2:$A${last_row}",
                "values":     f"='{sh}'!$C$2:$C${last_row}",
                "line":       {"color": "#ef5350", "width": 1.5, "dash_type": "dash"},
            })
            chart_evo.set_title({"name": "Crescita del Capitale"})
            chart_evo.set_size({"width": 800, "height": 400})
            ws_d.insert_chart("B4", chart_evo)

            chart_pnl = wb.add_chart({"type": "column"})
            chart_pnl.add_series({
                "name":       "Utile Netto",
                "categories": f"='{sh}'!$A$2:$A${last_row}",
                "values":     f"='{sh}'!$D$2:$D${last_row}",
                "fill":       {"color": "#66bb6a"},
                "gap":        50,
            })
            chart_pnl.set_title({"name": "Andamento Utile Netto (€)"})
            chart_pnl.set_size({"width": 800, "height": 350})
            ws_d.insert_chart("B26", chart_pnl)

        if rows_pf:
            chart_pie = wb.add_chart({"type": "doughnut"})
            chart_pie.add_series({
                "name":        "Allocazione",
                "categories":  f"='{sh_pf}'!$A$2:$A${len(rows_pf)+1}",
                "values":      f"='{sh_pf}'!$E$2:$E${len(rows_pf)+1}",
                "data_labels": {"percentage": True, "position": "outside"},
            })
            chart_pie.set_title({"name": "Allocazione Asset"})
            chart_pie.set_style(10)
            chart_pie.set_size({"width": 400, "height": 350})
            ws_d.insert_chart("O4", chart_pie)

        # ===================
        # FOGLIO 4: TRANSAZIONI
        # ===================
        if transactions:
            sh_tx = "Transazioni"
            df_tx = pd.DataFrame(transactions)
            # Normalizza colonne
            col_map = {
                "id": "ID", "symbol": "Asset", "quantity": "Qta",
                "price": "Prezzo", "date": "Data", "type": "Tipo", "fee": "Fee",
            }
            df_tx = df_tx.rename(columns=col_map)
            for col in ["ID", "Asset", "Qta", "Prezzo", "Data", "Tipo", "Fee"]:
                if col not in df_tx.columns:
                    df_tx[col] = ""
            df_tx["Totale (€)"] = pd.to_numeric(df_tx["Qta"], errors="coerce").fillna(0) \
                                 * pd.to_numeric(df_tx["Prezzo"], errors="coerce").fillna(0) \
                                 + pd.to_numeric(df_tx["Fee"], errors="coerce").fillna(0)
            df_tx["Data"] = pd.to_datetime(df_tx["Data"], errors="coerce").dt.strftime("%Y-%m-%d")
            df_tx = df_tx.sort_values("Data", ascending=False)
            df_tx.to_excel(writer, sheet_name=sh_tx, index=False)
            ws_tx = writer.sheets[sh_tx]
            ws_tx.set_column("A:A", 5)
            ws_tx.set_column("B:B", 10)
            ws_tx.set_column("C:C", 10)
            ws_tx.set_column("D:D", 12, fmt_currency)
            ws_tx.set_column("E:E", 12)
            ws_tx.set_column("F:F", 8)
            ws_tx.set_column("G:G", 10, fmt_currency)
            ws_tx.set_column("H:H", 15, fmt_currency)
            tx_len = len(df_tx) + 1
            ws_tx.conditional_format(1, 5, tx_len, 5, {"type": "cell", "criteria": "==", "value": '"BUY"', "format": fmt_txt_green})
            ws_tx.conditional_format(1, 5, tx_len, 5, {"type": "cell", "criteria": "==", "value": '"SELL"', "format": fmt_txt_red})

    return output.getvalue()
