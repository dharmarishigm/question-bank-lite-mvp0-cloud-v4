package com.meritiqra.app;
import static org.junit.Assert.*;
import android.content.Context;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
@RunWith(AndroidJUnit4.class)
public class SecureVaultTest {
 @Test public void encryptedPersistenceSurvivesRecreationAndRejectsTampering() throws Exception {
  Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();SecureVault vault=new SecureVault(context);JSONObject original=vault.read();
  try {
   vault.write(new JSONObject().put("qb_session","synthetic-secret-for-test").put("answers",new JSONObject().put("question-12","B")));
   String ciphertext=context.getSharedPreferences("meritiqra-secure",Context.MODE_PRIVATE).getString("ciphertext","");
   assertFalse(ciphertext.contains("synthetic-secret-for-test"));assertFalse(ciphertext.contains("question-12"));
   JSONObject restored=new SecureVault(context).read();assertEquals("synthetic-secret-for-test",restored.getString("qb_session"));assertEquals("B",restored.getJSONObject("answers").getString("question-12"));
   String changed=(ciphertext.charAt(0)=='A'?"B":"A")+ciphertext.substring(1);context.getSharedPreferences("meritiqra-secure",Context.MODE_PRIVATE).edit().putString("ciphertext",changed).commit();
   try {vault.read();fail("Authenticated encryption must reject a changed IV");}catch(javax.crypto.AEADBadTagException expected){}
  } finally {vault.write(original);}
 }
}
