import csv, os, sys, time
from dataclasses import dataclass
from typing import List, Optional
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QLineEdit,QPushButton,QTableWidget,QTableWidgetItem,QMessageBox,QSpinBox,QTextEdit,QGroupBox,QCheckBox,QFileDialog,QTabWidget
try:
    from pymodbus.client import ModbusTcpClient
except Exception:
    ModbusTcpClient=None

def resource_path(p):
    return os.path.join(getattr(sys,'_MEIPASS',os.path.abspath(os.path.join(os.path.dirname(__file__),'..'))),p)
def sf(v,d=0.0):
    try:
        return d if v is None or str(v).strip()=='' else float(v)
    except Exception: return d
def si(v,d=0):
    try: return int(float(v))
    except Exception: return d
@dataclass
class Parameter:
    model:str; reference:str; code:str; name:str; address:int; datatype:str; scale:float; default:float; min:float; max:float; unit:str; access:str; monitor:bool; write_protect:bool=False; notes:str=''; value:Optional[float]=None; online_value:Optional[float]=None; user_modified:bool=False
    @property
    def effective_value(self): return self.value if self.value is not None else self.default
class ParameterDB:
    def __init__(self): self.params=[]
    def load_csv(self,path):
        self.params=[]
        with open(path,newline='',encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                self.params.append(Parameter((r.get('model') or 'XD4000').strip(),(r.get('reference') or 'ALL').strip(),(r.get('code') or '').strip(),(r.get('name') or '').strip(),si(r.get('address')), (r.get('datatype') or 'uint16').strip().lower(), sf(r.get('scale'),1), sf(r.get('default')), sf(r.get('min'),-32768), sf(r.get('max'),65535), (r.get('unit') or '').strip(), (r.get('access') or 'RO').strip().upper(), str(r.get('monitor') or 'FALSE').upper() in ('TRUE','1','YES','Y'), str(r.get('write_protect') or 'FALSE').upper() in ('TRUE','1','YES','Y'), (r.get('notes') or '').strip()))
    def filtered(self,search='',monitor_only=False):
        s=(search or '').lower().strip(); out=[]
        for p in self.params:
            if monitor_only and not p.monitor: continue
            if s and not (s in p.code.lower() or s in p.name.lower() or s in str(p.address)): continue
            out.append(p)
        return out
    def by_code(self,code):
        for p in self.params:
            if p.code.upper()==code.upper(): return p
        return None
class ModbusGateway:
    def __init__(self): self.client=None; self.unit_id=1; self.address_offset=0
    def connect_tcp(self,host,port,unit_id,zero_based=False):
        if ModbusTcpClient is None: raise RuntimeError('pymodbus is not installed')
        self.unit_id=unit_id; self.address_offset=-1 if zero_based else 0
        self.client=ModbusTcpClient(host=host,port=port,timeout=3)
        if not self.client.connect(): raise RuntimeError('Could not connect to Modbus TCP device')
    def close(self):
        if self.client: self.client.close()
        self.client=None
    def is_connected(self): return self.client is not None
    def _addr(self,a):
        a=a+self.address_offset
        if a<0: raise RuntimeError(f'Invalid address after offset: {a}')
        return a
    def _kwargs(self): return [{'slave':self.unit_id},{'unit':self.unit_id},{'device_id':self.unit_id},{}]
    def read_registers(self,address,count=1):
        address=self._addr(address); last=None
        for kw in self._kwargs():
            try:
                rr=self.client.read_holding_registers(address=address,count=count,**kw)
                if rr.isError(): raise RuntimeError(str(rr))
                return rr.registers
            except TypeError as e: last=e; continue
        raise RuntimeError(f'read_holding_registers API failed: {last}')
    def write_register(self,address,value):
        address=self._addr(address); last=None
        for kw in self._kwargs():
            try:
                wr=self.client.write_register(address=address,value=value,**kw)
                if wr.isError(): raise RuntimeError(str(wr))
                return
            except TypeError as e: last=e; continue
            except Exception as e: last=e; break
        for kw in self._kwargs():
            try:
                wr=self.client.write_registers(address=address,values=[value],**kw)
                if wr.isError(): raise RuntimeError(str(wr))
                return
            except TypeError as e: last=e; continue
            except Exception as e: last=e; break
        raise RuntimeError(f'Write failed using FC06 and FC16: {last}')
    def read_param(self,p):
        regs=self.read_registers(p.address,2 if p.datatype in ('uint32','int32') else 1)
        if p.datatype=='int16': raw=regs[0] if regs[0]<32768 else regs[0]-65536
        elif p.datatype=='uint32': raw=(regs[0]<<16)+regs[1]
        elif p.datatype=='int32':
            raw=(regs[0]<<16)+regs[1]
            if raw>=2147483648: raw-=4294967296
        else: raw=regs[0]
        return raw*p.scale
    def write_param(self,p,val):
        if p.access!='RW': raise RuntimeError(f'{p.code} is read-only')
        raw=int(round(val/(p.scale if p.scale else 1)))
        if p.datatype=='int16' and raw<0: raw=65536+raw
        self.write_register(p.address,raw & 0xFFFF)
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle('LK XD4000 Phase-3 Channel Diagnosis Tester'); self.resize(1360,820)
        self.db=ParameterDB(); self.gateway=ModbusGateway(); self.params=[]; self.timer=QTimer(self); self.timer.timeout.connect(self.monitor_tick)
        self.build_ui(); self.load_db()
    def log(self,m): self.logbox.append(f'[{time.strftime("%H:%M:%S")}] {m}')
    def load_db(self):
        p=resource_path(os.path.join('data','xd4000_phase3_parameters.csv'))
        self.db.load_csv(p); self.refresh_params(); self.log(f'Loaded XD4000 Phase-3 database: {len(self.db.params)} parameters')
    def build_ui(self):
        c=QWidget(); self.setCentralWidget(c); root=QVBoxLayout(c); box=QGroupBox('XD4000 / ATV930 - Modbus TCP'); g=QGridLayout(box)
        self.host=QLineEdit('192.168.1.10'); self.port=QSpinBox(); self.port.setRange(1,65535); self.port.setValue(502); self.unit=QSpinBox(); self.unit.setRange(1,255); self.unit.setValue(1)
        self.zero=QCheckBox('Use zero-based address (-1)'); self.search=QLineEdit(); self.search.setPlaceholderText('Search code/name/address'); self.search.textChanged.connect(self.refresh_params); self.mononly=QCheckBox('Monitor only'); self.mononly.stateChanged.connect(self.refresh_params)
        for i,(lab,w) in enumerate([('Drive IP',self.host),('TCP Port',self.port),('Unit ID',self.unit),('Address option',self.zero),('Search',self.search),('Filter',self.mononly)]): g.addWidget(QLabel(lab),0,i); g.addWidget(w,1,i)
        for i,(txt,fn) in enumerate([('Connect',self.connect_drive),('Disconnect',self.disconnect_drive),('Upload visible',self.upload_visible),('Download selected row',self.download_selected),('Download modified RW',self.download_modified),('Export Event Log',self.export_log)]):
            b=QPushButton(txt); b.clicked.connect(fn); g.addWidget(b,2,i)
        root.addWidget(box); self.tabs=QTabWidget(); root.addWidget(self.tabs,1); self.table=QTableWidget(); self.tabs.addTab(self.table,'Parameters')
        cmd=QWidget(); cl=QVBoxLayout(cmd); self.expert=QCheckBox('Expert test mode: bench setup confirmed, output terminals safe'); cl.addWidget(self.expert)
        cl.addWidget(QLabel('CMD@8501 raw writes are locked. This tab diagnoses active command/reference channels and prepares command testing.'))
        row=QHBoxLayout()
        for txt,fn in [('Read ETA/RFR/FRH/LFR',self.read_command_status),('Diagnose CRC/CCC Channels',self.diagnose_channels),('Command Test Checklist',self.prepare_command_test_checklist),('Set LFR to 0.0 Hz',self.set_lfr_zero),('Start Monitor',self.start_monitor),('Stop Monitor',self.stop_monitor)]:
            b=QPushButton(txt); b.clicked.connect(fn); row.addWidget(b)
        cl.addLayout(row); self.command_status=QTextEdit(); self.command_status.setReadOnly(True); cl.addWidget(self.command_status); self.tabs.addTab(cmd,'Command Safety Test')
        self.logbox=QTextEdit(); self.logbox.setReadOnly(True); self.tabs.addTab(self.logbox,'Event Log')
    def refresh_params(self): self.params=self.db.filtered(self.search.text() if hasattr(self,'search') else '', self.mononly.isChecked() if hasattr(self,'mononly') else False); self.populate()
    def fmt(self,v):
        if v=='': return ''
        try: return f'{float(v):.3f}'.rstrip('0').rstrip('.')
        except Exception: return str(v)
    def populate(self):
        heads=['Code','Name','Address','Type','Scale','Default','Offline Value','Online Value','Unit','Access','Write Protect','Monitor','Notes']; self.table.blockSignals(True); self.table.setColumnCount(len(heads)); self.table.setHorizontalHeaderLabels(heads); self.table.setRowCount(len(self.params))
        for r,p in enumerate(self.params):
            vals=[p.code,p.name,p.address,p.datatype,p.scale,p.default,p.effective_value,'' if p.online_value is None else self.fmt(p.online_value),p.unit,p.access,'Yes' if p.write_protect else 'No','Yes' if p.monitor else 'No',p.notes]
            for col,v in enumerate(vals):
                it=QTableWidgetItem(str(v)); it.setFlags((it.flags()|Qt.ItemIsEditable) if col==6 and p.access=='RW' and not p.write_protect else (it.flags()&~Qt.ItemIsEditable)); self.table.setItem(r,col,it)
        self.table.blockSignals(False)
        try: self.table.itemChanged.disconnect()
        except Exception: pass
        self.table.itemChanged.connect(self.on_edit); self.table.resizeColumnsToContents()
    def on_edit(self,item):
        if item.column()!=6 or item.row()>=len(self.params): return
        p=self.params[item.row()]
        try:
            val=float(item.text());
            if not(p.min<=val<=p.max): raise ValueError(f'Allowed range: {p.min} to {p.max}')
            p.value=val; p.user_modified=True; self.log(f'Offline value changed: {p.code} = {val}')
        except Exception as e: QMessageBox.warning(self,'Invalid value',str(e))
    def connect_drive(self):
        try: self.gateway.connect_tcp(self.host.text().strip(),self.port.value(),self.unit.value(),self.zero.isChecked()); self.log(f'Connected successfully to {self.host.text().strip()}:{self.port.value()}, Unit ID={self.unit.value()}, zero_based={self.zero.isChecked()}')
        except Exception as e: self.log(f'Connection failed: {e}'); QMessageBox.critical(self,'Connection failed',str(e))
    def disconnect_drive(self): self.stop_monitor(); self.gateway.close(); self.log('Disconnected')
    def upload_one(self,p): p.online_value=self.gateway.read_param(p); p.value=p.online_value; p.user_modified=False; self.log(f'Upload OK {p.code}@{p.address} = {self.fmt(p.online_value)} {p.unit}'); return p.online_value
    def upload_visible(self):
        if not self.gateway.is_connected(): QMessageBox.warning(self,'Not connected','Connect first'); return
        ok=fail=0
        for p in self.params:
            try: self.upload_one(p); ok+=1
            except Exception as e: self.log(f'Upload failed {p.code}@{p.address}: {e}'); fail+=1
        self.populate(); self.log(f'Upload complete. OK={ok}, Failed={fail}')
    def write_rb(self,p):
        if p.write_protect and not self.expert.isChecked(): raise RuntimeError(f'{p.code} is write-protected. Expert mode required.')
        if p.code.upper()=='CMD': raise RuntimeError('CMD raw command writes are disabled in this safety build.')
        last=None
        for attempt in range(1,4):
            try: self.gateway.write_param(p,p.effective_value); self.log(f'Download OK {p.code}@{p.address} = {p.effective_value} {p.unit} on attempt {attempt}'); break
            except Exception as e: last=e; self.log(f'Download retry {attempt} failed {p.code}@{p.address}: {e}'); time.sleep(0.75*attempt)
        else: raise last
        rb=self.gateway.read_param(p); p.online_value=rb; p.value=rb; p.user_modified=False; self.log(f'Readback OK {p.code}@{p.address} = {self.fmt(rb)} {p.unit}')
    def selected_param(self):
        r=self.table.currentRow(); return self.params[r] if 0<=r<len(self.params) else None
    def download_selected(self):
        if not self.gateway.is_connected(): QMessageBox.warning(self,'Not connected','Connect first'); return
        p=self.selected_param()
        if not p: QMessageBox.warning(self,'No row selected','Select one parameter row first'); return
        if p.access!='RW': QMessageBox.warning(self,'Read-only',f'{p.code} is read-only'); return
        if QMessageBox.question(self,'Confirm selected write',f'Write {p.code}@{p.address} = {p.effective_value} {p.unit}?')!=QMessageBox.Yes: self.log('Selected write cancelled'); return
        try: self.write_rb(p); self.populate()
        except Exception as e: self.log(f'Selected write failed {p.code}@{p.address}: {e}')
    def download_modified(self):
        if not self.gateway.is_connected(): QMessageBox.warning(self,'Not connected','Connect first'); return
        if QMessageBox.question(self,'Confirm parameter download','This will write modified RW parameters. Continue?')!=QMessageBox.Yes: self.log('Download cancelled by user'); return
        ok=fail=0
        for p in self.params:
            diff=p.online_value is not None and abs(float(p.effective_value)-float(p.online_value))>1e-9
            if p.access=='RW' and (p.user_modified or diff):
                try: self.write_rb(p); ok+=1
                except Exception as e: self.log(f'Download failed {p.code}@{p.address}: {e}'); fail+=1
        self.populate(); self.log(f'Download complete. OK={ok}, Failed={fail}')
        if ok==0 and fail==0: self.log('No user-modified RW parameter found for download')
    def bit_text(self,val):
        labels={0:'Terminal/local',1:'Local keypad',2:'Remote keypad',3:'Modbus',6:'CANopen',9:'Fieldbus/comm module',11:'Embedded Ethernet',15:'SoMove/PC tool'}
        active=[f'bit {b}: {lab}' for b,lab in labels.items() if int(val)&(1<<b)]
        return ', '.join(active) if active else 'no known channel bit active'
    def read_codes(self,codes):
        lines=[]; vals={}
        for code in codes:
            p=self.db.by_code(code)
            if not p: lines.append(f'{code}: not in database'); continue
            try: v=self.gateway.read_param(p); p.online_value=v; p.value=v; vals[code]=v; lines.append(f'{code}@{p.address} = {self.fmt(v)} {p.unit}')
            except Exception as e: lines.append(f'{code}@{p.address} failed: {e}')
        return lines,vals
    def read_command_status(self):
        if not self.gateway.is_connected(): QMessageBox.warning(self,'Not connected','Connect first'); return
        lines,vals=self.read_codes(['ETA','RFR','FRH','LFR']); self.command_status.append(f'[{time.strftime("%H:%M:%S")}]\n'+'\n'.join(lines)+'\n'); self.log('Command status read completed'); self.refresh_params()
    def diagnose_channels(self):
        if not self.gateway.is_connected(): QMessageBox.warning(self,'Not connected','Connect first'); return
        lines,vals=self.read_codes(['ETA','HMIS','CRC','CCC','CNFS','LFT','COM1','RFR','FRH','LFR'])
        if 'CRC' in vals: lines.append(f'CRC active reference decode: {self.bit_text(vals["CRC"])}')
        if 'CCC' in vals: lines.append(f'CCC active command decode: {self.bit_text(vals["CCC"])}')
        if 'RFR' in vals: lines.append('Drive appears RUNNING or output frequency active. Avoid configuration writes.' if abs(float(vals['RFR']))>0.2 else 'Drive appears stopped / near zero output frequency.')
        self.command_status.append(f'[{time.strftime("%H:%M:%S")}] CHANNEL DIAGNOSIS\n'+'\n'.join(lines)+'\n'); self.log('Channel diagnosis completed'); self.refresh_params()
    def prepare_command_test_checklist(self):
        msg='Command test preparation only - no run command is written in this build.\n1. Confirm bench setup and output terminals are safe.\n2. Confirm ETA, HMIS, RFR read correctly.\n3. Confirm active command/reference channels using CCC and CRC.\n4. Confirm LFR reference path using safe values only.\n5. Keep CMD@8501 locked until command state-machine is implemented.\n'
        self.command_status.append(f'[{time.strftime("%H:%M:%S")}]\n{msg}'); self.log('Command test preparation checklist displayed')
    def set_lfr_zero(self):
        p=self.db.by_code('LFR')
        if p: p.value=0.0; p.user_modified=True; self.search.setText('LFR'); self.refresh_params(); self.log('Prepared LFR offline value = 0.0 Hz. Use Download selected row to write if safe.')
    def start_monitor(self):
        if not self.gateway.is_connected(): QMessageBox.warning(self,'Not connected','Connect first'); return
        self.timer.start(1000); self.log('Status monitor started at 1 s interval')
    def stop_monitor(self):
        if self.timer.isActive(): self.timer.stop(); self.log('Status monitor stopped')
    def monitor_tick(self): self.read_command_status()
    def export_log(self):
        path,_=QFileDialog.getSaveFileName(self,'Export event log','xd4000_event_log.txt','Text Files (*.txt)')
        if path:
            open(path,'w',encoding='utf-8').write(self.logbox.toPlainText()); self.log(f'Event log exported: {path}')
if __name__=='__main__':
    app=QApplication(sys.argv); w=MainWindow(); w.show(); sys.exit(app.exec())
