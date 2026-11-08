# PytaruiX: native file-drop fixture; only source and target windows owned by this test.
param([long]$Window, [uint32]$OwnerProcess, [string]$FilePath)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -ReferencedAssemblies System.Windows.Forms,System.Drawing -TypeDefinition @'
using System;
using System.Collections.Specialized;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Windows.Forms;
public class OwnedDropForm : Form {
    [StructLayout(LayoutKind.Sequential)] struct Point { public int X; public int Y; }
    [StructLayout(LayoutKind.Sequential)] struct Rect { public int L,T,R,B; }
    [DllImport("user32.dll")] static extern bool GetCursorPos(out Point point);
    [DllImport("user32.dll")] static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr window, out Rect rect);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window, out uint process);
    [DllImport("user32.dll")] static extern bool IsWindow(IntPtr window);
    [DllImport("user32.dll")] static extern bool IsChild(IntPtr parent, IntPtr child);
    [DllImport("user32.dll")] static extern IntPtr WindowFromPoint(Point point);
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr window);
    [DllImport("user32.dll")] static extern bool SetWindowPos(IntPtr window,IntPtr after,int x,int y,int width,int height,uint flags);
    [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr window,System.Text.StringBuilder text,int length);
    [DllImport("user32.dll")] static extern void mouse_event(uint flags, uint x, uint y, uint data, UIntPtr extra);
    IntPtr Target;
    uint TargetPid;
    string File;
    Point Original;
    Rect BoundsTarget;
    Timer Movement = new Timer();
    Timer StartDrag = new Timer();
    Timer Watchdog = new Timer();
    int Ticks;
    bool Pressed;
    bool Cancelled;
    bool RunningDrop;
    public DragDropEffects Result;
    public Exception Failure;
    public OwnedDropForm(long target, uint owner, string file) {
        Target = new IntPtr(target); TargetPid = owner; File = file;
        uint actual; GetWindowThreadProcessId(Target, out actual);
        if (actual != TargetPid || !IsWindow(Target)) throw new Exception("Unowned target");
        GetWindowRect(Target, out BoundsTarget); GetCursorPos(out Original);
        Console.WriteLine("TARGET_RECT " + BoundsTarget.L + "," + BoundsTarget.T + "," + BoundsTarget.R + "," + BoundsTarget.B);
        Text = "PytaruiX owned drop source";
        Width = 200; Height = 100; TopMost = true;
        StartPosition = FormStartPosition.Manual;
        Left = BoundsTarget.L + 20; Top = BoundsTarget.T + 20;
        Movement.Interval = 150;
        Movement.Tick += delegate {
            Ticks++;
            if (Ticks == 1) {
                SetForegroundWindow(Target);
                SetCursorPos((BoundsTarget.L + BoundsTarget.R)/2, (BoundsTarget.T + BoundsTarget.B)/2);
            }
            Point point; GetCursorPos(out point); IntPtr current = WindowFromPoint(point);
            bool owned = current == Target || IsChild(Target,current) || current == Handle || IsChild(Handle,current);
            Console.WriteLine("MOVE " + Ticks + " " + point.X + "," + point.Y + " " + current + " " + Target + " " + owned);
            if (!owned || Ticks > 20) Cancelled = true;
            if (Ticks == 3 || Cancelled) ReleaseButton();
        };
        QueryContinueDrag += delegate(object sender, QueryContinueDragEventArgs e) {
            if (Cancelled || e.EscapePressed) e.Action = DragAction.Cancel;
        };
        Watchdog.Interval = 4000;
        Watchdog.Tick += delegate { Cancelled = true; ReleaseButton(); if (!RunningDrop) Close(); };
        StartDrag.Interval = 300;
        StartDrag.Tick += delegate {
            StartDrag.Stop();
            SetForegroundWindow(Handle);
            SetWindowPos(Handle,new IntPtr(-1),0,0,0,0,0x43);
            Rect sourceRect; GetWindowRect(Handle,out sourceRect);
            SetCursorPos((sourceRect.L + sourceRect.R)/2, (sourceRect.T + sourceRect.B)/2);
            Point point; GetCursorPos(out point); IntPtr current = WindowFromPoint(point);
            if (current != Handle && !IsChild(Handle,current)) {
                uint blockedPid; GetWindowThreadProcessId(current,out blockedPid);
                System.Text.StringBuilder text = new System.Text.StringBuilder(256); GetWindowText(current,text,256);
                Console.WriteLine("BLOCKED " + blockedPid + " " + text.ToString());
                Failure = new Exception("Unowned source point"); Close(); return;
            }
            mouse_event(2,0,0,0,UIntPtr.Zero); Pressed = true;
        };
        MouseDown += delegate(object sender, MouseEventArgs e) { if (e.Button == MouseButtons.Left) RunDrop(); };
        Shown += delegate { Watchdog.Start(); StartDrag.Start(); };
        FormClosed += delegate { ReleaseButton(); Movement.Dispose(); StartDrag.Dispose(); Watchdog.Dispose(); };
    }
    void ReleaseButton() {
        if (Pressed) { mouse_event(4,0,0,0,UIntPtr.Zero); Pressed = false; }
    }
    void RunDrop() {
        try {
            RunningDrop = true;
            StringCollection files = new StringCollection(); files.Add(File);
            DataObject data = new DataObject(); data.SetFileDropList(files);
            Movement.Start();
            Result = DoDragDrop(data,DragDropEffects.Copy);
        } catch (Exception error) { Failure = error; }
        finally { RunningDrop = false; Movement.Stop(); ReleaseButton(); SetCursorPos(Original.X,Original.Y); Close(); }
    }
    public static void Run(long target, uint owner, string file) {
        using (OwnedDropForm form = new OwnedDropForm(target,owner,file)) {
            Application.Run(form);
            if (form.Failure != null) throw form.Failure;
            Console.WriteLine(form.Result);
            if (form.Result != DragDropEffects.Copy) throw new Exception("Native drop cancelled");
        }
    }
}
'@
[OwnedDropForm]::Run($Window,$OwnerProcess,(Resolve-Path -LiteralPath $FilePath).Path)
