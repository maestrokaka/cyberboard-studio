namespace CyberboardStudio;

internal enum WorkspaceExitIntent { CloseWindow, Reload }

// UI-thread state for one save barrier. Timeout or failure retires its token;
// a delayed WebView reply cannot approve a later close attempt.
internal sealed class WorkspaceExitGate
{
    public string? Token { get; private set; }
    public WorkspaceExitIntent? Intent { get; private set; }
    public bool IsPending => Token is not null;

    public string? Begin(WorkspaceExitIntent intent)
    {
        if (IsPending) return null;
        Token = Guid.NewGuid().ToString("N");
        Intent = intent;
        return Token;
    }

    public WorkspaceExitIntent? Finish(string token)
    {
        if (Token != token) return null;
        var intent = Intent;
        Token = null;
        Intent = null;
        return intent;
    }
}
