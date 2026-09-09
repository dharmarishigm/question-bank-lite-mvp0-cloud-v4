package com.meritiqra.app;

import android.content.Intent;
import android.net.Uri;
import android.util.Base64;
import android.view.WindowManager;
import com.getcapacitor.*;
import com.getcapacitor.annotation.CapacitorPlugin;
import org.json.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.util.*;
import java.util.concurrent.*;

@CapacitorPlugin(name="MeritIQra")
public class MeritIQraPlugin extends Plugin {
    private final ExecutorService executor=Executors.newSingleThreadExecutor();
    private final ExecutorService localExecutor=Executors.newSingleThreadExecutor();
    SecureVault vault;
    @Override public void load(){vault=new SecureVault(getContext());}
    private interface Task { JSObject run() throws Exception; }
    private void execute(PluginCall call,Task task){executor.execute(()->{try{call.resolve(task.run());}catch(Exception error){call.reject("The request could not complete. Check your connection and try again.");}});}
    private void executeLocal(PluginCall call,Task task){localExecutor.execute(()->{try{synchronized(vault){call.resolve(task.run());}}catch(Exception error){call.reject("Could not save local state. Please try again.");}});}
    private byte[] readBounded(InputStream input) throws IOException { ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] buffer=new byte[8192];int count;while((count=input.read(buffer))!=-1){if(out.size()+count>55*1024*1024)throw new IOException("Response too large");out.write(buffer,0,count);}return out.toByteArray();}
    private String random(){byte[] bytes=new byte[32];new SecureRandom().nextBytes(bytes);return Base64.encodeToString(bytes,Base64.URL_SAFE|Base64.NO_WRAP|Base64.NO_PADDING);}
    JSObject http(String path,String method,String body,JSArray files) throws Exception {
        if(!path.startsWith("/api/")&&!path.startsWith("/uploads/"))throw new SecurityException("Invalid endpoint");
        if(path.contains("\r")||path.contains("\n"))throw new SecurityException("Invalid endpoint");
        if(path.equals("/api/auth/logout")){String device=vault.read().optString("device_token");if(!device.isEmpty())http("/api/mobile/devices/current","DELETE",new JSONObject().put("token",device).toString(),null);}
        HttpURLConnection conn=(HttpURLConnection)new URL(BuildConfig.API_BASE_URL+path).openConnection();conn.setInstanceFollowRedirects(false);conn.setConnectTimeout(20000);conn.setReadTimeout(180000);conn.setRequestMethod(method);
        JSONObject state=vault.read();String cookie=state.optString("qb_session","");
        if(!cookie.isEmpty())conn.setRequestProperty("Cookie","qb_session="+cookie+"; qb_csrf="+state.optString("qb_csrf"));
        conn.setRequestProperty("X-CSRF-Token",state.optString("qb_csrf"));conn.setRequestProperty("X-MeritIQra-Client","android");conn.setRequestProperty("X-MeritIQra-Version",BuildConfig.VERSION_NAME);
        if(body!=null&&!method.equals("GET")){
            conn.setDoOutput(true);
            if(files!=null){
                String boundary="MeritIQra"+UUID.randomUUID();conn.setRequestProperty("Content-Type","multipart/form-data; boundary="+boundary);
                try(OutputStream output=conn.getOutputStream()){
                    JSONObject fields=new JSONObject(body);Iterator<String> keys=fields.keys();while(keys.hasNext()){String key=keys.next();output.write(("--"+boundary+"\r\nContent-Disposition: form-data; name=\""+key.replace("\"","")+"\"\r\n\r\n"+fields.getString(key)+"\r\n").getBytes(StandardCharsets.UTF_8));}
                    for(int i=0;i<files.length();i++){JSONObject file=files.getJSONObject(i);output.write(("--"+boundary+"\r\nContent-Disposition: form-data; name=\""+file.getString("key").replace("\"","")+"\"; filename=\""+file.getString("name").replaceAll("[\\r\\n\"]","")+"\"\r\nContent-Type: "+file.optString("type","application/octet-stream")+"\r\n\r\n").getBytes(StandardCharsets.UTF_8));output.write(Base64.decode(file.getString("data"),Base64.DEFAULT));output.write("\r\n".getBytes(StandardCharsets.UTF_8));}
                    output.write(("--"+boundary+"--\r\n").getBytes(StandardCharsets.UTF_8));
                }
            }else{conn.setRequestProperty("Content-Type","application/json");try(OutputStream out=conn.getOutputStream()){out.write(body.getBytes(StandardCharsets.UTF_8));}}
        }
        int status=conn.getResponseCode();
        JSONObject cookies=new JSONObject();
        for(Map.Entry<String,List<String>> entry:conn.getHeaderFields().entrySet())if("Set-Cookie".equalsIgnoreCase(entry.getKey()))for(String value:entry.getValue())for(String name:new String[]{"qb_session","qb_csrf"})if(value.startsWith(name+"="))cookies.put(name,value.substring(name.length()+1).split(";",2)[0]);
        InputStream input=status>=400?conn.getErrorStream():conn.getInputStream();byte[] bytes=input==null?new byte[0]:readBounded(input);if(input!=null)input.close();String text=new String(bytes,StandardCharsets.UTF_8);
        synchronized(vault){
        state=vault.read();for(String name:new String[]{"qb_session","qb_csrf"})if(cookies.has(name))state.put(name,cookies.get(name));
        if(status==200&&(path.equals("/api/auth/me")||path.equals("/api/mobile/auth/exchange"))){JSONObject user=new JSONObject(text);if(state.optLong("user_id")!=user.optLong("id")){state.remove("answers");state.remove("active_exam");}state.put("user_id",user.optLong("id"));}
        if(path.equals("/api/mobile/devices")&&method.equals("POST")&&status==200&&body!=null)state.put("device_token",new JSONObject(body).getString("token"));
        if(path.equals("/api/auth/logout")&&status==200)state=new JSONObject();
        vault.write(state);}
        JSObject result=new JSObject();result.put("status",status);result.put("body",text);result.put("contentType",conn.getContentType());result.put("binary",Base64.encodeToString(bytes,Base64.NO_WRAP));conn.disconnect();return result;
    }
    @PluginMethod public void request(PluginCall call){execute(call,()->http(call.getString("path",""),call.getString("method","GET"),call.getString("body"),call.getArray("files")));}
    @PluginMethod public void explorePublic(PluginCall call){getActivity().runOnUiThread(()->{getActivity().startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse(BuildConfig.API_BASE_URL+"/practice-exams")));call.resolve();});}
    @PluginMethod public void signIn(PluginCall call){execute(call,()->{
        String verifier=random();String challenge=Base64.encodeToString(MessageDigest.getInstance("SHA-256").digest(verifier.getBytes(StandardCharsets.US_ASCII)),Base64.URL_SAFE|Base64.NO_WRAP|Base64.NO_PADDING);
        JSObject response=http("/api/mobile/auth/start","POST",new JSONObject().put("challenge",challenge).toString(),null);if(response.getInteger("status")!=200)throw new IOException();
        String id=new JSONObject(response.getString("body")).getString("request_id");synchronized(vault){JSONObject state=vault.read();state.put("verifier",verifier);state.put("request_id",id);vault.write(state);}
        getActivity().runOnUiThread(()->getActivity().startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse(BuildConfig.API_BASE_URL+"/app?mobile_auth="+id))));return new JSObject();
    });}
    @PluginMethod public void completeSignIn(PluginCall call){execute(call,()->{
        JSONObject state=vault.read();if(!state.has("request_id"))return new JSObject();
        JSObject response=http("/api/mobile/auth/exchange","POST",new JSONObject().put("request_id",state.getString("request_id")).put("verifier",state.getString("verifier")).toString(),null);
        if(response.getInteger("status")==200){synchronized(vault){state=vault.read();state.remove("request_id");state.remove("verifier");vault.write(state);}}return new JSObject().put("authenticated",response.getInteger("status")==200);
    });}
    @PluginMethod public void acceptLink(PluginCall call){executeLocal(call,()->{
        Uri uri=Uri.parse(call.getString("url",""));Uri base=Uri.parse(BuildConfig.API_BASE_URL);if(!"https".equals(uri.getScheme())||!base.getHost().equals(uri.getHost()))throw new SecurityException();
        String path=uri.getPath();if(path==null||!(path.startsWith("/register/exam/")||path.startsWith("/exams/")||path.equals("/mobile/callback")))throw new SecurityException();
        JSONObject state=vault.read();if(!path.equals("/mobile/callback")){state.put("pending_link",path);vault.write(state);}return new JSObject();
    });}
    @PluginMethod public void context(PluginCall call){executeLocal(call,()->{JSONObject state=vault.read();return new JSObject().put("pending_link",state.optString("pending_link")).put("active_exam",state.optJSONObject("active_exam")==null?new JSONObject():state.optJSONObject("active_exam")).put("answers",state.optJSONObject("answers") == null?new JSONObject():state.optJSONObject("answers"));});}
    @PluginMethod public void examPosition(PluginCall call){executeLocal(call,()->{JSONObject state=vault.read();if(call.getInt("session",0)>0)state.put("active_exam",new JSONObject().put("session",call.getInt("session")).put("index",call.getInt("index",0)));else state.remove("active_exam");vault.write(state);return new JSObject();});}
    @PluginMethod public void clearLink(PluginCall call){executeLocal(call,()->{JSONObject state=vault.read();state.remove("pending_link");vault.write(state);return new JSObject();});}
    @PluginMethod public void queueAnswer(PluginCall call){executeLocal(call,()->{
        JSONObject state=vault.read();if(state.optLong("user_id")==0)throw new SecurityException();JSONObject answers=state.optJSONObject("answers");if(answers==null)answers=new JSONObject();String path=call.getString("path","");if(!path.matches("/api/sessions/[0-9]+/answers/[0-9]+"))throw new SecurityException();
        answers.put(path,new JSONObject().put("body",call.getString("body","{}")).put("operation_id",UUID.randomUUID().toString()).put("timestamp",System.currentTimeMillis()));state.put("answers",answers);vault.write(state);return new JSObject().put("pending",answers.length());
    });}
    @PluginMethod public void syncAnswers(PluginCall call){execute(call,()->{
        JSONObject state=vault.read(),answers=state.optJSONObject("answers");if(answers==null)return new JSObject().put("pending",0);
        List<String> paths=new ArrayList<>();answers.keys().forEachRemaining(paths::add);int rejected=0;
        for(String path:paths){JSONObject operation=answers.getJSONObject(path);JSObject r=http(path,"PUT",operation.getString("body"),null);int code=r.getInteger("status");if(code==200||code==404||code==409){if(code!=200)rejected++;synchronized(vault){JSONObject latest=vault.read();JSONObject pending=latest.optJSONObject("answers");if(pending!=null&&pending.has(path)&&pending.getJSONObject(path).optString("operation_id").equals(operation.optString("operation_id"))){pending.remove(path);latest.put("answers",pending);vault.write(latest);}}}else break;}
        JSONObject pending=vault.read().optJSONObject("answers");return new JSObject().put("pending",pending==null?0:pending.length()).put("rejected",rejected);
    });}
    @PluginMethod public void protectedWindow(PluginCall call){boolean enabled=call.getBoolean("enabled",false);getActivity().runOnUiThread(()->{if(enabled)getActivity().getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);else getActivity().getWindow().clearFlags(WindowManager.LayoutParams.FLAG_SECURE);call.resolve();});}
    @PluginMethod public void exit(PluginCall call){getActivity().runOnUiThread(()->{getActivity().finish();call.resolve();});}
}
