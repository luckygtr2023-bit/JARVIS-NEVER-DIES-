package com.brahma.connect.pairing

import android.content.Context
import android.os.Build
import com.brahma.connect.core.DeviceCredential
import com.brahma.connect.core.PairingOffer
import org.json.JSONObject
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

class PairingStorage(context: Context) {
    private val prefs = EncryptedSharedPreferences.create(
        context,
        "brahma_connect_secure",
        MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    fun saveCredential(credential: DeviceCredential) {
        prefs.edit()
            .putString("device_credential", JSONObject()
                .put("device_id", credential.deviceId)
                .put("device_secret", credential.deviceSecret)
                .put("device_name", credential.deviceName)
                .put("gateway_host", credential.gatewayHost)
                .put("gateway_port", credential.gatewayPort)
                .put("paired_at", credential.pairedAt)
                .toString())
            .apply()
    }

    fun loadCredential(): DeviceCredential? {
        val raw = prefs.getString("device_credential", null) ?: return null
        return try {
            val json = JSONObject(raw)
            val deviceId = json.optString("device_id")
            val deviceSecret = json.optString("device_secret")
            val gatewayHost = json.optString("gateway_host")
            val gatewayPort = json.optInt("gateway_port", 0)
            // Fail closed: a corrupt, partial or loopback trust record is
            // treated as absent and cleared rather than silently used.
            if (deviceId.isBlank() || deviceSecret.isBlank() || gatewayHost.isBlank() ||
                gatewayPort <= 0 || gatewayPort > 65535
            ) {
                clearCredential()
                return null
            }
            DeviceCredential(
                deviceId = deviceId,
                deviceSecret = deviceSecret,
                deviceName = json.optString("device_name", Build.MODEL),
                gatewayHost = gatewayHost,
                gatewayPort = gatewayPort,
                pairedAt = json.optString("paired_at"),
            )
        } catch (_: Exception) {
            clearCredential()
            null
        }
    }

    fun clearCredential() {
        prefs.edit().remove("device_credential").apply()
    }

    fun saveGatewayHint(offer: PairingOffer) {
        prefs.edit()
            .putString("last_pairing_offer", offer.toJson().toString())
            .apply()
    }

    fun loadGatewayHint(): PairingOffer? {
        val raw = prefs.getString("last_pairing_offer", null) ?: return null
        return try {
            val offer = PairingOffer.fromJson(JSONObject(raw))
            if (offer.host.isBlank() || offer.host.equals("localhost", true) ||
                offer.host == "127.0.0.1" || offer.port <= 0 || offer.port > 65535
            ) {
                prefs.edit().remove("last_pairing_offer").apply()
                null
            } else {
                offer
            }
        } catch (_: Exception) {
            prefs.edit().remove("last_pairing_offer").apply()
            null
        }
    }
}
