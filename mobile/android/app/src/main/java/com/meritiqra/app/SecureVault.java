package com.meritiqra.app;

import android.content.Context;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import org.json.JSONObject;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** Only ciphertext is stored in preferences; the AES key never leaves Android Keystore. */
final class SecureVault {
    private final Context context;
    SecureVault(Context context) { this.context=context; }
    private SecretKey key() throws Exception {
        KeyStore store=KeyStore.getInstance("AndroidKeyStore");store.load(null);
        if(!store.containsAlias("meritiqra-session")) {
            KeyGenerator generator=KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder("meritiqra-session",KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT).setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());generator.generateKey();
        }
        return (SecretKey)store.getKey("meritiqra-session",null);
    }
    synchronized JSONObject read() throws Exception {
        String stored=context.getSharedPreferences("meritiqra-secure",Context.MODE_PRIVATE).getString("ciphertext",null);
        if(stored==null)return new JSONObject();
        byte[] encoded=Base64.decode(stored,Base64.NO_WRAP),iv=java.util.Arrays.copyOfRange(encoded,0,12),data=java.util.Arrays.copyOfRange(encoded,12,encoded.length);
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.DECRYPT_MODE,key(),new GCMParameterSpec(128,iv));
        return new JSONObject(new String(cipher.doFinal(data),java.nio.charset.StandardCharsets.UTF_8));
    }
    synchronized void write(JSONObject value) throws Exception {
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.ENCRYPT_MODE,key());byte[] encrypted=cipher.doFinal(value.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));
        byte[] all=new byte[12+encrypted.length];System.arraycopy(cipher.getIV(),0,all,0,12);System.arraycopy(encrypted,0,all,12,encrypted.length);
        if(!context.getSharedPreferences("meritiqra-secure",Context.MODE_PRIVATE).edit().putString("ciphertext",Base64.encodeToString(all,Base64.NO_WRAP)).commit())throw new java.io.IOException("Secure persistence failed");
    }
}
