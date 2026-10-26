using System.Drawing.Drawing2D;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Text.RegularExpressions;
namespace CyberboardStudio;

internal sealed class CompanionDesktop : Form
{
    private readonly JsonElement catalog;
    private JsonElement preferences;
    private Bitmap? picture,idle;
    private string pictureKey="";
    private string theme="dark",taskState="idle",title="",message="",zone="";
    private bool expanded,dragging,suspended,consumed,initialized;
    private Point dragStart;
    private DateTime entered=DateTime.MinValue,lastGlobal=DateTime.MinValue,reactionEnd=DateTime.MinValue,taskEnd=DateTime.MaxValue;
    private readonly Dictionary<string,DateTime> lastZones=new();
    private readonly System.Windows.Forms.Timer poll=new(){Interval=67};
    private readonly Button submit=new(),cancel=new();
    private readonly TextBox transcript=new();
    private Rectangle art,bubble;
    private readonly string settingsFile=Path.Combine(HostPaths.State,"companion-desktop.json");
    private readonly string positionFile=Path.Combine(HostPaths.State,"companion-position.json");
    private readonly Func<bool> canInteract;
    internal event Action? OpenTask;
    internal event Action? CancelTask;
    internal event Action? DismissTask;
    internal event Action<string>? SubmitTask;
    internal event Action? PreferencesChanged;
    internal JsonElement Preferences=>preferences.Clone();
    internal CompanionDesktop(Func<bool> canInteract)
    {
        this.canInteract=canInteract;
        using var json=JsonDocument.Parse(File.ReadAllText(Path.Combine(HostPaths.Web,"assets/companion/catalog.json")));catalog=json.RootElement.Clone();
        preferences=catalog.GetProperty("defaults").Clone();
        try{if(File.Exists(settingsFile))preferences=Validate(JsonSerializer.Deserialize<JsonElement>(File.ReadAllText(settingsFile)));}catch(Exception e)when(e is IOException or UnauthorizedAccessException or JsonException or ArgumentException or InvalidOperationException){ }
        FormBorderStyle=FormBorderStyle.None;ShowInTaskbar=false;TopMost=true;DoubleBuffered=true;BackColor=TransparencyKey=Color.Fuchsia;
        StartPosition=FormStartPosition.Manual;AccessibleName="喵娘桌面陪伴，可拖动";
        submit.Text="查看任务";submit.Click+=(_,_)=>{if(taskState=="awaitingConfirmation")SubmitTask?.Invoke(transcript.Text);else OpenTask?.Invoke();};
        cancel.Text="收起";cancel.Click+=(_,_)=>
        {
            if(taskState=="idle"){suspended=true;StopAudio();ResetHover();Hide();}
            else if(taskState is "completed" or "error" or "cancelled")DismissTask?.Invoke();
            else CancelTask?.Invoke();
        };
        Controls.Add(submit);Controls.Add(cancel);Controls.Add(transcript);
        MouseDown+=(_,e)=>{if(e.Button==MouseButtons.Right){MenuAt(e.Location);return;}if(e.Button==MouseButtons.Left){dragging=true;dragStart=Cursor.Position;Capture=true;StopAudio();ResetHover();}};
        MouseMove+=(_,e)=>{if(dragging){var next=Cursor.Position;Location=new Point(Left+next.X-dragStart.X,Top+next.Y-dragStart.Y);dragStart=next;}};
        MouseUp+=(_,_)=>EndDrag();MouseCaptureChanged+=(_,_)=>{if(dragging&&!Capture)EndDrag();};
        DoubleClick+=(_,_)=>OpenTask?.Invoke();poll.Tick+=(_,_)=>Tick();
        ApplyStyle();RestorePosition();initialized=true;if(Resident&&!suspended)Show();poll.Start();
    }
    protected override bool ShowWithoutActivation=>true;
    protected override CreateParams CreateParams{get{var p=base.CreateParams;p.ExStyle|=0x80;return p;}}
    private bool Resident=>MiaoCallContracts.Text(preferences,"mode")=="resident";
    internal JsonElement Validate(JsonElement p)
    {
        if(p.ValueKind!=JsonValueKind.Object)throw new IOException("桌面陪伴设置无效，请重新选择。");
        var outfit=MiaoCallContracts.Text(p,"outfit");bool valid=catalog.GetProperty("outfits").EnumerateArray().Any(o=>MiaoCallContracts.Text(o,"id")==outfit)||ValidCustom(outfit);
        if(!valid||MiaoCallContracts.Text(p,"mode") is not("resident" or "wake")||MiaoCallContracts.Text(p,"voice") is not("sweet" or "mature" or "gentle" or "playful")||!p.TryGetProperty("size",out var s)||s.ValueKind!=JsonValueKind.Number||!s.TryGetDouble(out var size)||!double.IsFinite(size)||size is <240 or >440||!p.TryGetProperty("volume",out var v)||v.ValueKind!=JsonValueKind.Number||!v.TryGetDouble(out var volume)||!double.IsFinite(volume)||volume is <0 or >1||!p.TryGetProperty("sound",out var sound)||sound.ValueKind is not(JsonValueKind.True or JsonValueKind.False)||!p.TryGetProperty("hover",out var hover)||hover.ValueKind is not(JsonValueKind.True or JsonValueKind.False))throw new IOException("桌面陪伴设置无效，请重新选择。");
        return JsonSerializer.SerializeToElement(new {outfit,mode=MiaoCallContracts.Text(p,"mode"),voice=MiaoCallContracts.Text(p,"voice"),sound=sound.GetBoolean(),hover=hover.GetBoolean(),size,volume});
    }
    private bool ValidCustom(string id)=>Regex.IsMatch(id,"\\Acustom-[0-9a-f]{32}\\z")&&File.Exists(Path.Combine(HostPaths.State,"companion-outfits",id+".png"));
    internal void Save(JsonElement p)
    {
        var value=Validate(p);Atomic(settingsFile,value);preferences=value;suspended=false;ApplyStyle();PreferencesChanged?.Invoke();
    }
    internal static void Atomic(string path,object value)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);var temp=path+"."+Guid.NewGuid().ToString("N")+".tmp";
        try{File.WriteAllText(temp,JsonSerializer.Serialize(value));File.Move(temp,path,true);}finally{if(File.Exists(temp))File.Delete(temp);}
    }
    internal object[] CustomOutfits()
    {
        var folder=Path.Combine(HostPaths.State,"companion-outfits");if(!Directory.Exists(folder))return [];
        var outfits=new List<object>();
        foreach(var path in Directory.GetFiles(folder,"*.png").Where(p=>ValidCustom(Path.GetFileNameWithoutExtension(p))).Order().TakeLast(20))
        {
            try
            {
                using var source=new Bitmap(path);using var thumb=new Bitmap(100,200);using(var g=Graphics.FromImage(thumb)){g.InterpolationMode=InterpolationMode.HighQualityBicubic;g.DrawImage(source,new Rectangle(0,0,100,200));}
                using var stream=new MemoryStream();thumb.Save(stream,System.Drawing.Imaging.ImageFormat.Png);
                string hair="short";try{using var d=JsonDocument.Parse(File.ReadAllText(Path.ChangeExtension(path,".json")));hair=MiaoCallContracts.Text(d.RootElement,"hair","short");}catch(Exception e)when(e is IOException or UnauthorizedAccessException or JsonException){}
                outfits.Add(new{id=Path.GetFileNameWithoutExtension(path),name="AI 衣装",builtin=false,staticPose=true,hair,imageDataUrl="data:image/png;base64,"+Convert.ToBase64String(stream.ToArray())});
            }
            catch(Exception e)when(e is IOException or UnauthorizedAccessException or ArgumentException or ExternalException){ } // One damaged local outfit must not hide the settings page.
        }
        return outfits.ToArray();
    }
    private Bitmap LoadPicture(string pose)
    {
        string outfit=MiaoCallContracts.Text(preferences,"outfit"),path;
        if(ValidCustom(outfit))
        {
            try{using var custom=new Bitmap(Path.Combine(HostPaths.State,"companion-outfits",outfit+".png"));return new Bitmap(custom);}
            catch(Exception e)when(e is IOException or UnauthorizedAccessException or ArgumentException or ExternalException){outfit="sailor-short";}
        }
        {
            var selected=catalog.GetProperty("outfits").EnumerateArray().FirstOrDefault(o=>MiaoCallContracts.Text(o,"id")==outfit);
            if(selected.ValueKind!=JsonValueKind.Object)selected=catalog.GetProperty("outfits")[0];
            var frames=selected.GetProperty("frames");var relative=MiaoCallContracts.Text(frames,pose,MiaoCallContracts.Text(frames,"idle"));path=Path.Combine(HostPaths.Web,relative.Replace('/',Path.DirectorySeparatorChar));
        }
        using var source=new Bitmap(path);return new Bitmap(source);
    }
    private void Pose(string pose)
    {
        var key=MiaoCallContracts.Text(preferences,"outfit")+"/"+pose;if(picture!=null&&pictureKey==key)return;
        var next=LoadPicture(pose);picture?.Dispose();picture=next;pictureKey=key;Invalidate();
    }
    internal void ApplyTheme(string value)
    {
        theme=value;bool light=theme=="island";var text=light?Color.FromArgb(114,81,46):Color.FromArgb(239,240,242);
        foreach(var b in new[]{submit,cancel}){b.FlatStyle=FlatStyle.Flat;b.FlatAppearance.BorderSize=1;b.FlatAppearance.BorderColor=light?Color.FromArgb(204,195,169):Color.FromArgb(69,70,74);b.ForeColor=text;b.BackColor=b==submit?(light?Color.FromArgb(15,188,174):Color.FromArgb(244,128,65)):(light?Color.FromArgb(247,243,226):Color.FromArgb(40,41,45));b.Font=new Font("Microsoft YaHei UI",9,FontStyle.Bold);}
        transcript.BackColor=light?Color.FromArgb(250,247,231):Color.FromArgb(33,34,37);transcript.ForeColor=text;Invalidate();
    }
    internal void ApplyStyle()
    {
        if(taskState!="idle")return;expanded=false;idle?.Dispose();idle=LoadPicture("idle");Pose("idle");LayoutPet();
        if(initialized&&Resident&&!suspended)Show();else Hide();ResetHover();
    }
    private void LayoutPet()
    {
        int h=(int)preferences.GetProperty("size").GetDouble(),w=h/2;var anchor=PointToScreen(new Point(art.Left,0));
        var area=Screen.FromPoint(anchor).WorkingArea;bool left=expanded&&anchor.X+w+348>area.Right;
        art=new Rectangle(left?348:0,0,w,h);bubble=new Rectangle(left?0:w-6,Math.Max(8,h-182),348,180);
        ClientSize=new Size(w+(expanded?354:8),h+6);Location=new Point(Math.Clamp(anchor.X-art.Left,area.Left,Math.Max(area.Left,area.Right-Width)),Math.Clamp(anchor.Y,area.Top,Math.Max(area.Top,area.Bottom-Height)));
        bool confirm=taskState=="awaitingConfirmation",view=taskState is "awaitingApproval" or "awaitingInput" or "completed";
        transcript.Visible=expanded&&confirm;transcript.Bounds=new Rectangle(bubble.X+20,bubble.Y+101,308,27);
        submit.Visible=expanded&&(confirm||view);submit.Text=confirm?"交给 Codex":"查看任务";submit.Bounds=new Rectangle(bubble.X+184,bubble.Bottom-43,143,29);
        cancel.Visible=expanded;cancel.Text=taskState is "idle" or "completed" or "error" or "cancelled"?"收起":"取消";cancel.Bounds=new Rectangle(bubble.X+(submit.Visible?79:229),bubble.Bottom-43,91,29);Invalidate();
    }
    internal void State(string state,string text,string recognized="")
    {
        taskState=state;message=text;expanded=state!="idle";reactionEnd=DateTime.MinValue;StopAudio();ResetHover();
        title=state switch{"configuring"=>"正在准备连接","preparing"=>"正在准备语音","listening"=>"正在听你说","transcribing"=>"正在识别语音","awaitingConfirmation"=>"听清楚啦，确认一下？","connecting"=>"正在连接 Codex","thinking"=>"Codex 正在思考","acting"=>"Codex 正在处理任务","awaitingApproval"=>"Codex 需要你的授权","awaitingInput"=>"Codex 需要补充信息","completed"=>"Codex 已返回结果","cancelling"=>"正在停止任务","cancelled"=>"任务已停止",_=>"需要你看一下"};
        if(state=="idle"){ApplyStyle();return;}Pose(state=="completed"?"happy":state=="listening"?"ears":state=="thinking"?"think":"idle");transcript.Text=recognized;
        taskEnd=state is "completed" or "error" or "cancelled"?DateTime.UtcNow.AddSeconds(12):DateTime.MaxValue;
        suspended=false;LayoutPet();Show();
    }
    private void ResetHover(){zone="";consumed=false;entered=DateTime.MinValue;}
    private JsonElement? Zone(Point p)
    {
        if(idle==null||!art.Contains(p))return null;double x=(p.X-art.X)/(double)art.Width,y=(p.Y-art.Y)/(double)art.Height;
        if(idle.GetPixel(Math.Clamp((int)(x*idle.Width),0,idle.Width-1),Math.Clamp((int)(y*idle.Height),0,idle.Height-1)).A<40)return null;
        foreach(var z in catalog.GetProperty("zones").EnumerateArray()){var r=z.GetProperty("rect").EnumerateArray().Select(v=>v.GetDouble()).ToArray();if(x>=r[0]&&x<=r[0]+r[2]&&y>=r[1]&&y<=r[1]+r[3])return z;}
        return null;
    }
    private void Tick()
    {
        var now=DateTime.UtcNow;if(!Visible||dragging)return;
        if(taskState!="idle"){if(taskEnd<now)State("idle","");return;}
        if(reactionEnd<now&&reactionEnd!=DateTime.MinValue){reactionEnd=DateTime.MinValue;expanded=false;Pose("idle");LayoutPet();if(!Resident){Hide();return;}}
        if(!canInteract()||!MiaoCallContracts.Flag(preferences,"hover")){StopAudio();ResetHover();return;}
        var z=Zone(PointToClient(Cursor.Position));var id=z.HasValue?MiaoCallContracts.Text(z.Value,"id"):"";
        if(id!=zone){zone=id;entered=now;consumed=false;return;}
        if(id.Length==0||consumed||reactionEnd>now||now-entered<TimeSpan.FromMilliseconds(480)||now-lastGlobal<TimeSpan.FromSeconds(3.2)||now-lastZones.GetValueOrDefault(id,DateTime.MinValue)<TimeSpan.FromSeconds(9))return;
        consumed=true;lastGlobal=lastZones[id]=now;React(id,false,null);
    }
    internal void React(string id,bool force,JsonElement? settings)
    {
        if(taskState!="idle"||!canInteract())return;var z=catalog.GetProperty("zones").EnumerateArray().FirstOrDefault(v=>MiaoCallContracts.Text(v,"id")==id);if(z.ValueKind!=JsonValueKind.Object)return;
        title="轻触 · "+MiaoCallContracts.Text(z,"name");message=MiaoCallContracts.Text(z,"text");Pose(MiaoCallContracts.Text(z,"pose","idle"));expanded=true;reactionEnd=DateTime.UtcNow.AddSeconds(2.4);LayoutPet();Show();
        var p=settings??preferences;if(force||MiaoCallContracts.Flag(p,"sound"))PlayAudio(MiaoCallContracts.Text(p,"voice","sweet"),id,p.GetProperty("volume").GetDouble());
    }
    private void PlayAudio(string voice,string id,double volume)
    {
        StopAudio();var path=Path.Combine(HostPaths.Web,"assets/companion/audio",voice,id+".mp3");if(!File.Exists(path)||path.Contains('"'))return;
        if(mciSendString("open \""+path+"\" type mpegvideo alias miaocall_voice",IntPtr.Zero,0,IntPtr.Zero)==0){mciSendString("setaudio miaocall_voice volume to "+(int)(volume*1000),IntPtr.Zero,0,IntPtr.Zero);mciSendString("play miaocall_voice",IntPtr.Zero,0,IntPtr.Zero);}
    }
    private void StopAudio()=>mciSendString("close miaocall_voice",IntPtr.Zero,0,IntPtr.Zero);
    private void MenuAt(Point p)
    {
        var menu=new ContextMenuStrip();menu.Items.Add("查看任务",null,(_,_)=>OpenTask?.Invoke());menu.Items.Add("暂时收起",null,(_,_)=>{suspended=true;StopAudio();ResetHover();Hide();});menu.Items.Add("取消当前任务",null,(_,_)=>CancelTask?.Invoke());menu.Closed+=(_,_)=>menu.Dispose();menu.Show(this,p);
    }
    private Point ClampLocation(Point value)
    {
        var area=Screen.FromPoint(new Point(value.X+art.Left,value.Y)).WorkingArea;
        return new Point(Math.Clamp(value.X,area.Left,Math.Max(area.Left,area.Right-Width)),Math.Clamp(value.Y,area.Top,Math.Max(area.Top,area.Bottom-Height)));
    }
    private void RestorePosition()
    {
        var area=Screen.PrimaryScreen?.WorkingArea??SystemInformation.WorkingArea;
        var fallback=ClampLocation(new Point(area.Right-Width-24,area.Bottom-Height-24));Location=fallback;
        try
        {
            using var d=JsonDocument.Parse(File.ReadAllText(positionFile));var p=d.RootElement;
            if(p.ValueKind==JsonValueKind.Object&&p.TryGetProperty("x",out var x)&&x.ValueKind==JsonValueKind.Number&&x.TryGetInt32(out var px)&&p.TryGetProperty("y",out var y)&&y.ValueKind==JsonValueKind.Number&&y.TryGetInt32(out var py))Location=ClampLocation(new Point(px-art.Left,py));
        }
        catch(Exception e)when(e is IOException or UnauthorizedAccessException or JsonException or ArgumentException){Location=fallback;}
    }
    private void EndDrag()
    {
        if(!dragging)return;dragging=false;Capture=false;Location=ClampLocation(Location);SavePosition();ResetHover();
    }
    private void SavePosition(){try{Atomic(positionFile,new{x=Left+art.Left,y=Top});}catch(Exception e)when(e is IOException or UnauthorizedAccessException){}}
    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);var g=e.Graphics;g.SmoothingMode=SmoothingMode.AntiAlias;g.InterpolationMode=InterpolationMode.HighQualityBicubic;
        if(picture!=null)g.DrawImage(picture,art);
        if(!expanded)return;bool light=theme=="island";
        using var shape=Rounded(bubble,22);using var fill=new SolidBrush(light?Color.FromArgb(255,253,242):Color.FromArgb(18,19,21));using var border=new Pen(light?Color.FromArgb(206,198,176):Color.FromArgb(71,72,77),1.5f);g.FillPath(fill,shape);g.DrawPath(border,shape);
        using var font=new Font("Microsoft YaHei UI",11,FontStyle.Bold);using var body=new Font("Microsoft YaHei UI",10);var color=light?Color.FromArgb(122,80,37):Color.FromArgb(255,150,80);
        TextRenderer.DrawText(g,title,font,new Rectangle(bubble.X+20,bubble.Y+17,308,28),color,TextFormatFlags.EndEllipsis);
        TextRenderer.DrawText(g,message,body,new Rectangle(bubble.X+20,bubble.Y+53,308,taskState=="awaitingConfirmation"?45:75),light?Color.FromArgb(114,87,56):Color.FromArgb(234,235,238),TextFormatFlags.WordBreak|TextFormatFlags.EndEllipsis);
    }
    private static GraphicsPath Rounded(Rectangle r,int radius){var p=new GraphicsPath();int d=radius*2;p.AddArc(r.X,r.Y,d,d,180,90);p.AddArc(r.Right-d,r.Y,d,d,270,90);p.AddArc(r.Right-d,r.Bottom-d,d,d,0,90);p.AddArc(r.X,r.Bottom-d,d,d,90,90);p.CloseFigure();return p;}
    protected override void Dispose(bool disposing){if(disposing){poll.Stop();poll.Dispose();StopAudio();picture?.Dispose();idle?.Dispose();}base.Dispose(disposing);}
    [DllImport("winmm.dll",CharSet=CharSet.Unicode)]private static extern uint mciSendString(string command,IntPtr output,int length,IntPtr callback);
}
