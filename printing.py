"""Windows GDI printing with job-local A4 / 100% / long-edge settings."""
import sys

def printers():
    if sys.platform!='win32': return [],''
    import win32print
    names=sorted({p[2] for p in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL|win32print.PRINTER_ENUM_CONNECTIONS)})
    try:default=win32print.GetDefaultPrinter()
    except Exception:default=''
    return names,default

def print_pdf(path,printer,duplex=True,copies=1):
    if sys.platform!='win32': raise RuntimeError('Прямая печать доступна только в Windows.')
    if not 1<=copies<=99:raise ValueError('Количество копий: от 1 до 99.')
    import fitz
    import win32print,win32gui,win32ui,win32con
    from PIL import Image, ImageWin
    h=win32print.OpenPrinter(printer);dc=None;started=False
    try:
        dm=win32print.GetPrinter(h,2)['pDevMode']
        if dm is None:raise RuntimeError('Драйвер не предоставил настройки печати.')
        dm.Fields|=win32con.DM_ORIENTATION|win32con.DM_PAPERSIZE|win32con.DM_DUPLEX|win32con.DM_COPIES
        dm.Orientation=win32con.DMORIENT_PORTRAIT;dm.PaperSize=win32con.DMPAPER_A4
        dm.Duplex=win32con.DMDUP_VERTICAL if duplex else win32con.DMDUP_SIMPLEX;dm.Copies=1
        desired=dm.Duplex
        result=win32print.DocumentProperties(0,h,printer,dm,dm,win32con.DM_IN_BUFFER|win32con.DM_OUT_BUFFER)
        if result!=1:raise RuntimeError('Драйвер отклонил настройки печати.')
        if dm.Duplex!=desired or dm.PaperSize!=win32con.DMPAPER_A4 or dm.Orientation!=win32con.DMORIENT_PORTRAIT:
            raise RuntimeError('Принтер не подтвердил A4 / книжную ориентацию / нужный режим сторон. Используйте отдельную печать лицевых и оборота.')
        dc=win32ui.CreateDCFromHandle(win32gui.CreateDC('WINSPOOL',printer,dm))
        dx,dy=dc.GetDeviceCaps(88),dc.GetDeviceCaps(90)
        ox,oy=dc.GetDeviceCaps(112),dc.GetDeviceCaps(113)
        pw,ph=dc.GetDeviceCaps(110),dc.GetDeviceCaps(111)
        rw,rh=dc.GetDeviceCaps(8),dc.GetDeviceCaps(10)
        if max(ox*72/dx,oy*72/dy,(pw-rw-ox)*72/dx,(ph-rh-oy)*72/dy)>19:
            raise RuntimeError('Непечатные поля принтера слишком велики. Сохраните PDF и проверьте предпросмотр в программе печати.')
        dc.StartDoc('ContractPrintApp');started=True
        with fitz.open(str(path)) as doc:
            for copy in range(copies):
                for page in doc:
                    pix=page.get_pixmap(matrix=fitz.Matrix(250/72,250/72),colorspace=fitz.csRGB,alpha=False)
                    img=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
                    dc.StartPage()
                    ImageWin.Dib(img).draw(dc.GetHandleOutput(),(-ox,-oy,round(page.rect.width*dx/72)-ox,round(page.rect.height*dy/72)-oy))
                    dc.EndPage()
                if duplex and len(doc)%2:dc.StartPage();dc.EndPage()
        dc.EndDoc();started=False
    except Exception:
        if started and dc:
            try:dc.AbortDoc()
            except Exception:pass
        raise
    finally:
        if dc:dc.DeleteDC()
        win32print.ClosePrinter(h)
