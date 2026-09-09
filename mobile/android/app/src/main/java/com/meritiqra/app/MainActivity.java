package com.meritiqra.app;

import android.os.Bundle;
import android.webkit.WebView;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.util.Base64;
import com.getcapacitor.*;
import java.io.ByteArrayInputStream;
import java.util.Map;

public class MainActivity extends BridgeActivity {
    @Override public void onCreate(Bundle savedInstanceState){
        registerPlugin(MeritIQraPlugin.class);super.onCreate(savedInstanceState);
        // Capacitor's default java.net cookie bridge must not capture native session cookies.
        // Authentication belongs exclusively to the Keystore vault and explicit HTTP headers.
        java.net.CookieHandler.setDefault(null);
        android.webkit.CookieManager.getInstance().setAcceptCookie(false);
        android.webkit.CookieManager.getInstance().removeAllCookies(null);
        bridge.setWebViewClient(new BridgeWebViewClient(bridge){
            @Override public WebResourceResponse shouldInterceptRequest(WebView view,WebResourceRequest request){
                String path=request.getUrl().getEncodedPath();
                if("localhost".equals(request.getUrl().getHost())&&(path.startsWith("/uploads/")||path.matches("/api/sources/[^/]+/pages/[0-9]+"))){
                    try{
                        MeritIQraPlugin plugin=(MeritIQraPlugin)bridge.getPlugin("MeritIQra").getInstance();
                        JSObject result=plugin.http(path,"GET",null,null);int status=result.getInteger("status");
                        return new WebResourceResponse(result.getString("contentType","application/octet-stream"),null,status,status==200?"OK":"Unavailable",java.util.Collections.singletonMap("Cache-Control","no-store"),new ByteArrayInputStream(Base64.decode(result.getString("binary"),Base64.NO_WRAP)));
                    }catch(Exception error){return new WebResourceResponse("text/plain","UTF-8",503,"Unavailable",java.util.Collections.singletonMap("Cache-Control","no-store"),new ByteArrayInputStream(new byte[0]));}
                }
                return super.shouldInterceptRequest(view,request);
            }
        });
    }
}
