package icu.forddream.linguascene;

import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
    }

    @Override
    public void onBackPressed() {
        // 物理返回键优先回退 WebView 内的浏览历史（Next.js 走 History API，canGoBack 能识别），
        // 只有退无可退时才交给 Capacitor 默认逻辑（退出 App），避免一点返回就直接关掉。
        if (getBridge() != null
                && getBridge().getWebView() != null
                && getBridge().getWebView().canGoBack()) {
            getBridge().getWebView().goBack();
            return;
        }
        super.onBackPressed();
    }
}