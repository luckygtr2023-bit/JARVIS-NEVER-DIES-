package com.brahma.connect.pairing

import com.brahma.connect.core.PairingOffer
import org.json.JSONObject

object PairingPayloadParser {
    fun parse(raw: String): PairingOffer? {
        if (raw.isBlank()) return null
        return try {
            val offer = PairingOffer.fromJson(JSONObject(raw))
            // Reject payloads that cannot reach a real gateway (loopback on
            // Android is the phone itself) or are structurally invalid.
            if (offer.host.isBlank() || offer.host.equals("localhost", true) ||
                offer.host == "127.0.0.1" || offer.port <= 0 || offer.port > 65535 ||
                offer.pairingToken.isBlank() || offer.expiresInSeconds < 0
            ) {
                null
            } else {
                offer
            }
        } catch (_: Exception) {
            null
        }
    }
}
