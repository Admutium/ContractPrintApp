"""Bounded GUI readiness check: process window events before inspecting images."""
import time

def preview_state(app):
    return {'canvas':[app.pcanvas.winfo_width(),app.pcanvas.winfo_height()],
            'mapped':bool(app.pcanvas.winfo_ismapped()),
            'page_image':getattr(app,'tkimage',None) is not None,
            'thumbnails':len(app.thumb_images),'pdf_pages':len(app.pdf) if app.pdf is not None else 0}

def wait_for_preview(app,timeout=8,clock=time.monotonic,pause=time.sleep):
    deadline=clock()+timeout
    while True:
        app.root.update()
        if app.pcanvas.winfo_ismapped() and app.pcanvas.winfo_width()>=30 and app.pcanvas.winfo_height()>=30:
            app.render();app.draw_thumbnails()
        state=preview_state(app)
        if state['mapped'] and min(state['canvas'])>=30 and state['page_image'] and state['thumbnails']:
            return state
        if clock()>=deadline:raise RuntimeError('Предпросмотр не готов после ожидания: '+str(state))
        pause(.02)
