package pk.aasra.app;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.ContentValues;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Bundle;
import android.provider.MediaStore;
import android.text.InputType;
import android.view.Gravity;
import android.view.ViewGroup;
import android.webkit.JavascriptInterface;
import android.webkit.PermissionRequest;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;

/**
 * Aasra (آسرا, "support"; prototype): the widow-support assistant as an Android app.
 *
 * The app is the phone side: microphone, camera, screen, speaker. The thinking (Whisper speech
 * recognition, document OCR, the claim rules, the database) runs on the server - for the demo, the
 * laptop - and the app shows its assistant screen (/assistant) in a full-screen WebView, so everything
 * tested on the web works the same here.
 *
 * Server address: set once, either from a link (aasra://setup?server=https://...; the web login page
 * shows an "Open in app" button that sends it) or typed on the setup screen. It is kept on the phone.
 */
public class MainActivity extends Activity {

    private static final String PREFS = "aasra";
    private static final String KEY_SERVER = "server";
    private static final int REQ_MEDIA_PERMS = 10;
    private static final int REQ_CAMERA_FOR_FILE = 11;
    private static final int REQ_FILE = 20;
    private static final String START_PATH = "/assistant";
    /** The free ngrok link shows browsers a warning page first; the app skips it with this header. */
    private static final Map<String, String> HEADERS = Collections.singletonMap("ngrok-skip-browser-warning", "1");

    private FrameLayout root;
    private WebView web;
    private PermissionRequest pendingPermission;
    private ValueCallback<Uri[]> fileCallback;
    private WebChromeClient.FileChooserParams pendingFileParams;
    private Uri cameraOutput;

    // ------------------------------------------------------------------ life cycle
    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        root = new FrameLayout(this);
        root.setBackgroundColor(Color.parseColor("#f6f6f2"));
        root.setFitsSystemWindows(true);   // Android 15 draws apps edge to edge: keep clear of the status bar
        setContentView(root);
        getWindow().setStatusBarColor(Color.parseColor("#0b6b3a"));
        takeServerFromLink(getIntent());
        if (server() == null) showSetup(null); else showApp(state);
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        if (takeServerFromLink(intent)) showApp(null);
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        if (web != null) web.saveState(out);
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.getParent() != null && web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }

    @Override
    protected void onDestroy() {
        if (web != null) web.destroy();
        super.onDestroy();
    }

    // ------------------------------------------------------------------ server address
    private SharedPreferences prefs() {
        return getSharedPreferences(PREFS, MODE_PRIVATE);
    }

    /** The address set on this phone, else the one built into the app (android/server.txt), else none. */
    private String server() {
        String saved = prefs().getString(KEY_SERVER, null);
        return saved != null ? saved : cleanServer(BuildConfig.DEFAULT_SERVER);
    }

    /** "abc.trycloudflare.com" -> "https://abc.trycloudflare.com"; "192.168.1.5:8080" -> "http://192.168.1.5:8080". */
    static String cleanServer(String raw) {
        if (raw == null) return null;
        String s = raw.trim();
        if (s.isEmpty()) return null;
        if (!s.startsWith("http://") && !s.startsWith("https://")) {
            boolean local = s.matches("^(\\d{1,3}\\.){3}\\d{1,3}(:\\d+)?(/.*)?$") || s.startsWith("localhost");
            s = (local ? "http://" : "https://") + s;
        }
        Uri u = Uri.parse(s);
        if (u.getHost() == null || u.getHost().isEmpty()) return null;
        return u.getScheme() + "://" + u.getHost() + (u.getPort() > 0 ? ":" + u.getPort() : "");
    }

    private boolean takeServerFromLink(Intent intent) {
        Uri data = intent == null ? null : intent.getData();
        if (data == null || !"aasra".equals(data.getScheme())) return false;
        String s = cleanServer(data.getQueryParameter("server"));
        if (s == null) return false;
        prefs().edit().putString(KEY_SERVER, s).apply();
        return true;
    }

    // ------------------------------------------------------------------ setup screen (first start / change server)
    private void showSetup(String message) {
        root.removeAllViews();
        LinearLayout box = column();
        box.addView(text("آسرا · Aasra", 32, true, "#0b6b3a"));
        box.addView(text("بیوہ امداد اسسٹنٹ · Widow support assistant (prototype)", 17, false, "#5b5b5b"));
        if (message != null) box.addView(text(message, 17, true, "#b91c1c"));
        box.addView(text("سرور کا پتہ · Server address", 18, true, "#1a1a1a"));
        final EditText field = new EditText(this);
        field.setHint("your-name.ngrok-free.dev");
        field.setText(server() == null ? "" : server());
        field.setTextSize(20);
        field.setSingleLine(true);
        field.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        box.addView(field);
        Button go = bigButton("✓  جڑیں · Connect", "#15803d");
        go.setOnClickListener(v -> {
            String s = cleanServer(field.getText().toString());
            if (s == null) { showSetup("پتہ درست نہیں · Not a valid address"); return; }
            prefs().edit().putString(KEY_SERVER, s).apply();
            showApp(null);
        });
        box.addView(go);
        box.addView(text("آسان طریقہ: لیپ ٹاپ پر demo.bat چلائیں۔ فون پر اس کا https لنک کروم میں کھولیں اور "
                + "'ایپ میں کھولیں' دبائیں۔\n\nEasiest: run demo.bat on the laptop, open its https link in Chrome on "
                + "this phone and tap 'Open in app'. The address is then filled in for you.", 16, false, "#1a1a1a"));
        ScrollView scroll = new ScrollView(this);
        scroll.addView(box);
        root.addView(scroll);
    }

    // ------------------------------------------------------------------ the app: the assistant screen
    @SuppressLint({"SetJavaScriptEnabled", "JavascriptInterface"})
    private void showApp(Bundle state) {
        root.removeAllViews();
        if (web == null) {
            web = new WebView(this);
            WebSettings ws = web.getSettings();
            ws.setJavaScriptEnabled(true);
            ws.setDomStorageEnabled(true);                    // the login token and screen state
            ws.setMediaPlaybackRequiresUserGesture(false);    // the assistant speaks each answer aloud
            ws.setAllowFileAccess(false);
            ws.setAllowContentAccess(true);
            ws.setTextZoom(100);
            ws.setUserAgentString(ws.getUserAgentString() + " AasraApp/0.1");
            web.addJavascriptInterface(new Bridge(), "LMNative");
            web.setWebViewClient(new Client());
            web.setWebChromeClient(new Chrome());
        }
        root.addView(web, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));
        if (state != null && web.restoreState(state) != null) return;
        web.loadUrl(server() + START_PATH, HEADERS);
        askMediaPermissions();   // ask once at the start, in the app's own words, not in the middle of a question
    }

    private void showOffline() {
        root.removeAllViews();
        LinearLayout box = column();
        box.addView(text("📶", 54, false, "#1a1a1a"));
        box.addView(text("کنکشن نہیں مل رہا۔ آپ کا کام محفوظ ہے۔", 22, true, "#1a1a1a"));
        box.addView(text("Cannot reach the server. Your work is saved.\nIs the laptop on, with demo.bat running? "
                + "The link changes each time demo.bat starts.", 16, false, "#5b5b5b"));
        Button retry = bigButton("🔁  دوبارہ کوشش · Try again", "#15803d");
        retry.setOnClickListener(v -> showApp(null));
        box.addView(retry);
        Button change = bigButton("⚙️  سرور بدلیں · Change server", "#1d4ed8");
        change.setOnClickListener(v -> showSetup(null));
        box.addView(change);
        root.addView(box);
    }

    private class Client extends WebViewClient {
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            Uri u = request.getUrl();
            Uri home = Uri.parse(server());
            if (home.getHost() != null && home.getHost().equals(u.getHost())) {   // our own pages
                view.loadUrl(u.toString(), HEADERS);
                return true;
            }
            try {   // anything else (e.g. a help link) opens in the phone's browser
                startActivity(new Intent(Intent.ACTION_VIEW, u));
            } catch (ActivityNotFoundException ignored) { }
            return true;
        }

        @Override
        public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
            if (request.isForMainFrame()) runOnUiThread(MainActivity.this::showOffline);
        }

        /** The tunnel answers 502/530 when the laptop or the app on it is off. */
        @Override
        public void onReceivedHttpError(WebView view, WebResourceRequest request, WebResourceResponse response) {
            if (request.isForMainFrame() && response.getStatusCode() >= 500) runOnUiThread(MainActivity.this::showOffline);
        }
    }

    private class Chrome extends WebChromeClient {
        /** The page asks for the microphone (her voice) or the camera (the CNIC / certificate photo). */
        @Override
        public void onPermissionRequest(final PermissionRequest request) {
            runOnUiThread(() -> {
                List<String> missing = missingFor(request.getResources());
                if (missing.isEmpty()) {
                    request.grant(request.getResources());
                } else {
                    pendingPermission = request;
                    requestPermissions(missing.toArray(new String[0]), REQ_MEDIA_PERMS);
                }
            });
        }

        /** <input type=file>: the photo fallback when the live camera cannot be used. */
        @Override
        public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
            if (fileCallback != null) fileCallback.onReceiveValue(null);
            fileCallback = callback;
            pendingFileParams = params;
            if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{Manifest.permission.CAMERA}, REQ_CAMERA_FOR_FILE);
            } else {
                openFileChooser();
            }
            return true;
        }
    }

    /** window.LMNative in the page: lets the assistant screen offer "change server" inside the app. */
    private class Bridge {
        @JavascriptInterface
        public void changeServer() {
            runOnUiThread(() -> showSetup(null));
        }

        @JavascriptInterface
        public String version() {
            return "0.1";
        }
    }

    // ------------------------------------------------------------------ permissions
    private void askMediaPermissions() {
        List<String> missing = new ArrayList<>();
        for (String p : new String[]{Manifest.permission.RECORD_AUDIO, Manifest.permission.CAMERA}) {
            if (checkSelfPermission(p) != PackageManager.PERMISSION_GRANTED) missing.add(p);
        }
        if (!missing.isEmpty()) requestPermissions(missing.toArray(new String[0]), 0);
    }

    private List<String> missingFor(String[] resources) {
        List<String> missing = new ArrayList<>();
        for (String r : resources) {
            String p = PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(r) ? Manifest.permission.RECORD_AUDIO
                    : PermissionRequest.RESOURCE_VIDEO_CAPTURE.equals(r) ? Manifest.permission.CAMERA : null;
            if (p != null && checkSelfPermission(p) != PackageManager.PERMISSION_GRANTED) missing.add(p);
        }
        return missing;
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(code, permissions, results);
        if (code == REQ_MEDIA_PERMS && pendingPermission != null) {
            PermissionRequest r = pendingPermission;
            pendingPermission = null;
            if (missingFor(r.getResources()).isEmpty()) r.grant(r.getResources()); else r.deny();
        } else if (code == REQ_CAMERA_FOR_FILE) {
            openFileChooser();   // without the camera permission it still offers the gallery
        }
    }

    // ------------------------------------------------------------------ photo picker (camera or gallery)
    private void openFileChooser() {
        Intent pick = pendingFileParams != null ? pendingFileParams.createIntent()
                : new Intent(Intent.ACTION_GET_CONTENT).setType("image/*");
        pick.addCategory(Intent.CATEGORY_OPENABLE);
        Intent chooser = Intent.createChooser(pick, "تصویر · Photo");
        cameraOutput = null;
        if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            try {
                ContentValues v = new ContentValues();
                v.put(MediaStore.Images.Media.DISPLAY_NAME, "aasra_" + System.currentTimeMillis() + ".jpg");
                v.put(MediaStore.Images.Media.MIME_TYPE, "image/jpeg");
                cameraOutput = getContentResolver().insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, v);
                if (cameraOutput != null) {
                    Intent camera = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
                    camera.putExtra(MediaStore.EXTRA_OUTPUT, cameraOutput);
                    camera.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
                    boolean cameraFirst = pendingFileParams != null && pendingFileParams.isCaptureEnabled();
                    if (cameraFirst) chooser = camera;
                    else chooser.putExtra(Intent.EXTRA_INITIAL_INTENTS, new Intent[]{camera});
                }
            } catch (Exception ignored) {
                cameraOutput = null;   // no storage access: gallery only
            }
        }
        try {
            startActivityForResult(chooser, REQ_FILE);
        } catch (ActivityNotFoundException e) {
            if (fileCallback != null) fileCallback.onReceiveValue(null);
            fileCallback = null;
        }
    }

    @Override
    protected void onActivityResult(int code, int result, Intent data) {
        super.onActivityResult(code, result, data);
        if (code != REQ_FILE || fileCallback == null) return;
        Uri[] picked = null;
        if (result == RESULT_OK) {
            if (data != null && data.getData() != null) picked = new Uri[]{data.getData()};
            else if (cameraOutput != null) picked = new Uri[]{cameraOutput};
        } else if (cameraOutput != null) {
            try { getContentResolver().delete(cameraOutput, null, null); } catch (Exception ignored) { }
        }
        fileCallback.onReceiveValue(picked);
        fileCallback = null;
        pendingFileParams = null;
    }

    // ------------------------------------------------------------------ small UI helpers (no layout files)
    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    private LinearLayout column() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(24), dp(40), dp(24), dp(24));
        box.setGravity(Gravity.CENTER_HORIZONTAL);
        return box;
    }

    private TextView text(String s, int sp, boolean bold, String color) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(sp);
        t.setTextColor(Color.parseColor(color));
        if (bold) t.setTypeface(Typeface.DEFAULT_BOLD);
        t.setGravity(Gravity.CENTER);
        t.setPadding(0, dp(8), 0, dp(8));
        return t;
    }

    private Button bigButton(String label, String color) {
        Button b = new Button(this);
        b.setText(label);
        b.setTextSize(20);
        b.setAllCaps(false);
        b.setTextColor(Color.WHITE);
        b.setBackgroundColor(Color.parseColor(color));
        b.setMinHeight(dp(64));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.setMargins(0, dp(12), 0, dp(4));
        b.setLayoutParams(lp);
        return b;
    }
}
