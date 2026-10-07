"""Scratch: all 24 key pills plus the wheel mark, both themes, one image."""
import os, sys
os.environ["QT_QPA_PLATFORM"]="offscreen"
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap, QPainter, QColor
from PySide6.QtCore import QSize
app=QApplication([])
import direction as d
img=QPixmap(2*(24+13*70), 2*170); img.setDevicePixelRatio(2)
p=QPainter(img)
for row,(light,pal) in enumerate(((False,d.HARMONIC_DARK),(True,d.HARMONIC_LIGHT))):
    y0=row*85
    p.fillRect(0,y0,24+13*70,85,QColor(pal.BG_SURFACE))
    p.drawPixmap(12,y0+12,d.wheel_pixmap(light,44))
    for n in range(1,13):
        for j,m in enumerate("AB"):
            ic=d.key_chip(f"{n}{m}",120+n,light,pal)
            p.drawPixmap(70+(n-1)*70, y0+18+j*28, ic.pixmap(QSize(62,18)))
p.end(); img.save(sys.argv[1])
