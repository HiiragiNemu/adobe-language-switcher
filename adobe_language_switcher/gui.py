"""Small Chinese-first Tk interface. Workers return receipts; no silent elevation."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import uuid
from . import __version__, windows
from .adapters import build_plan, inspect_installation
from .resources import SwitchError
from .transaction import Engine


class App:
    def __init__(self, root):
        self.root=root;self.busy=False;self.plan=None
        root.title(f'Adobe Language Switcher {__version__} | Adobe 界面语言切换')
        root.geometry('1040x740');root.minsize(880,630)
        style=ttk.Style();style.theme_use('clam')
        style.configure('TFrame',background='#f4f6fa')
        style.configure('TLabel',background='#f4f6fa',font=('Microsoft YaHei UI',10))
        style.configure('Title.TLabel',font=('Microsoft YaHei UI',21,'bold'),foreground='#182f55')
        style.configure('TButton',padding=(13,8),font=('Microsoft YaHei UI',10))
        panel=ttk.Frame(root,padding=24);panel.pack(fill='both',expand=True)
        ttk.Label(panel,text='Adobe 界面语言切换',style='Title.TLabel').pack(anchor='w')
        ttk.Label(panel,text='本地资源 · 常规设置 / 兼容映射 · 自动备份 · 一键恢复').pack(anchor='w',pady=(3,18))
        row=ttk.Frame(panel);row.pack(fill='x')
        self.path=tk.StringVar()
        ttk.Label(row,text='安装目录').pack(side='left')
        self.path_box=ttk.Combobox(row,textvariable=self.path,width=66);self.path_box.pack(side='left',fill='x',expand=True,padx=10)
        ttk.Button(row,text='浏览',command=self.browse).pack(side='left')
        ttk.Button(row,text='检测',command=self.inspect).pack(side='left',padx=(7,0))
        options=ttk.Frame(panel);options.pack(fill='x',pady=14)
        self.mode=tk.StringVar(value='常规设置');self.target=tk.StringVar(value='zh_CN');self.carrier=tk.StringVar(value='fr_FR')
        for label,var,values,width in [('模式',self.mode,['常规设置','兼容映射'],13),('目标语言',self.target,['zh_CN','en_US','ja_JP','de_DE','fr_FR'],13),('承载语言',self.carrier,['fr_FR','de_DE','ja_JP'],13)]:
            ttk.Label(options,text=label).pack(side='left',padx=(0,6))
            combo=ttk.Combobox(options,textvariable=var,values=values,width=width,state='readonly')
            combo.pack(side='left',padx=(0,18))
            if label=='目标语言':self.targets=combo
            if label=='承载语言':self.carriers=combo
        self.confirmed=tk.BooleanVar()
        ttk.Checkbutton(panel,text='兼容映射：我已确认上述承载语言能正常启动（内部语言保留该值，只替换界面文字）',variable=self.confirmed).pack(anchor='w')
        ttk.Label(panel,text='请先保存并退出 Adobe 应用。缺少目标语言包会停止；不会下载资源或强制关闭程序。').pack(anchor='w',pady=(7,12))
        self.text=tk.Text(panel,height=15,wrap='word',font=('Microsoft YaHei UI',10),bg='white',fg='#23354d',relief='flat',padx=13,pady=10)
        self.text.pack(fill='both',expand=True)
        actions=ttk.Frame(panel);actions.pack(fill='x',pady=12)
        ttk.Button(actions,text='预览变更',command=self.preview).pack(side='left')
        self.apply_button=ttk.Button(actions,text='一键切换',command=self.apply);self.apply_button.pack(side='left',padx=10)
        ttk.Button(actions,text='启动应用检查',command=self.launch).pack(side='left')
        self.status=tk.StringVar(value='检测安装后，选择目标语言并预览。')
        ttk.Label(panel,textvariable=self.status).pack(anchor='w')
        history=ttk.Frame(panel);history.pack(fill='x',pady=(12,0))
        self.history=ttk.Combobox(history,state='readonly',width=62)
        self.history.pack(side='left',fill='x',expand=True)
        ttk.Button(history,text='刷新记录',command=self.refresh).pack(side='left',padx=8)
        ttk.Button(history,text='一键恢复',command=self.restore).pack(side='left')
        ttk.Label(panel,text='首版实机验证：Premiere 26.5.2.5。AE / AME / Audition 为实验性词典映射；部分首页与插件文字可能保留原语言。').pack(anchor='w',pady=(12,0))
        self.say('欢迎。工具仅处理本机已安装的语言资源与首选项。\n常规设置：使用 Premiere 的语言偏好。\n兼容映射：将目标文字映射到可正常启动的非英文语言，适用于已验证的第三方打包环境。\n软件来源不是兼容性保证；每次都检查实际资源结构。')
        self.root.after(150,self.detect)

    def say(self,text):
        self.text.config(state='normal');self.text.delete('1.0','end');self.text.insert('end',text);self.text.config(state='disabled')

    def error(self,exc):
        self.status.set('操作未完成；请查看提示。');messagebox.showerror('提示',str(exc))

    def detect(self):
        try:
            apps=windows.discover();self.path_box['values']=[str(x.root) for x in apps]
            if apps and not self.path.get():self.path.set(str(apps[0].root));self.inspect()
            self.refresh()
        except Exception as exc:self.error(exc)

    def browse(self):
        chosen=filedialog.askdirectory(title='选择 Adobe 应用安装目录')
        if chosen:self.path.set(chosen);self.inspect()

    def inspect(self):
        try:
            app=inspect_installation(self.path.get())
            self.targets['values']=app.locales;self.carriers['values']=[x for x in app.locales if x!='en_US']
            if self.target.get() not in app.locales and app.locales:self.target.set(app.locales[0])
            if self.carrier.get() not in app.locales:self.carrier.set(next((x for x in app.locales if x!='en_US'),''))
            self.say(json.dumps(app.summary(),ensure_ascii=False,indent=2));self.status.set('检测完成；尚未修改文件。')
        except Exception as exc:self.error(exc)

    def make_plan(self):
        return build_plan(inspect_installation(self.path.get()),self.target.get(),'mapped' if self.mode.get()=='兼容映射' else 'native',self.carrier.get(),confirmed=self.confirmed.get())

    def preview(self):
        try:
            self.plan=self.make_plan();self.say(json.dumps(self.plan.summary(),ensure_ascii=False,indent=2));self.status.set(f'预览：{len(self.plan.edits)} 个文件；尚未写入。')
        except Exception as exc:self.error(exc)

    def worker(self,arguments):
        if self.busy:raise SwitchError('上一操作尚未完成，请等待。')
        folder=windows.state_root()/'receipts';folder.mkdir(parents=True,exist_ok=True)
        receipt=folder/(uuid.uuid4().hex+'.json')
        args=[*arguments,'--expected-user',windows.user_identity(),'--receipt',str(receipt)]
        self.busy=True;self.apply_button.config(state='disabled');self.status.set('正在处理；若出现管理员确认，请检查后允许。')
        try:
            if not windows.is_admin():windows.elevate(args)
            else:subprocess.Popen(windows.worker_command(args),cwd=Path(__file__).resolve().parents[1],creationflags=0x08000000)
        except Exception:
            self.busy=False;self.apply_button.config(state='normal');raise
        deadline=time.monotonic()+300
        def poll():
            if receipt.exists():
                result=json.loads(receipt.read_text(encoding='utf-8'))
                self.busy=False;self.apply_button.config(state='normal');self.refresh()
                self.say(json.dumps(result,ensure_ascii=False,indent=2))
                self.status.set('文件操作完成；请启动应用确认界面。' if result['ok'] else '操作失败；详情见上方。')
            elif time.monotonic()>deadline:
                self.busy=False;self.apply_button.config(state='normal');self.status.set('尚未收到结果。先刷新记录检查状态，不要重复操作。')
            else:self.root.after(500,poll)
        self.root.after(500,poll)

    def apply(self):
        try:
            plan=self.make_plan()
            self.say(json.dumps(plan.summary(),ensure_ascii=False,indent=2))
            if not messagebox.askyesno('确认切换',f'将修改 {len(plan.edits)} 个文件及所需语言偏好。\n已保存并退出 Adobe 应用？\n备份保存在本机，失败可恢复。'):return
            args=['apply',str(plan.app.root),'--target',plan.target,'--mode',plan.mode,'--yes']
            if plan.mode=='mapped':args+=['--carrier',plan.carrier,'--carrier-confirmed']
            self.worker(args)
        except Exception as exc:self.error(exc)

    def refresh(self):
        self.records=Engine().histories()
        labels=[f'{x["id"]} | {x["status"]} | {x["target"]}' for x in self.records]
        self.history['values']=labels
        if labels:self.history.current(0)

    def restore(self):
        try:
            index=self.history.current()
            if index<0:raise SwitchError('没有可恢复的记录。手工修改产生的旧备份不会自动导入。')
            item=self.records[index]
            if messagebox.askyesno('恢复',f'恢复事务 {item["id"]}？\n请先保存并退出 Adobe 应用。'):
                self.worker(['restore',item['id'],'--yes'])
        except Exception as exc:self.error(exc)

    def launch(self):
        try:
            if self.busy:raise SwitchError('请等待文件操作完成。')
            app=inspect_installation(self.path.get());subprocess.Popen([str(app.exe)],cwd=app.exe.parent)
            self.status.set('已发出启动请求，尚未确认成功；若报错，关闭提示后使用一键恢复。')
        except Exception as exc:self.error(exc)


def run():
    if os.name!='nt':raise SwitchError('图形工具目前仅支持 Windows')
    root=tk.Tk();App(root);root.mainloop()
