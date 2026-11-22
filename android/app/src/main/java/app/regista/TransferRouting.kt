package app.regista

/** Route choice uses actual local subnets, never the mere presence of a charging cable. */
data class ImportSubnet(val name:String,val address:String,val prefix:Int)

object TransferRouting {
    fun usb(name:String)=listOf("usb","rndis","ncm").any { name.startsWith(it) }
    private fun number(address:String):Long? {
        val parts=address.split('.').map { it.toIntOrNull() ?: return null }
        if (parts.size!=4 || parts.any { it !in 0..255 }) return null
        return parts.fold(0L) { value,part -> (value shl 8) or part.toLong() }
    }
    fun contains(subnet:ImportSubnet,address:String):Boolean {
        if (subnet.prefix !in 8..32) return false
        val mask=(0xffffffffL shl (32-subnet.prefix)) and 0xffffffffL
        val own=number(subnet.address) ?: return false
        val peer=number(address) ?: return false
        return (own and mask)==(peer and mask)
    }
    fun transport(address:String,subnets:List<ImportSubnet>):String {
        val matching=subnets.filter { contains(it,address) }
        return when {
            matching.any { usb(it.name) } -> "usb"
            matching.any { it.name.startsWith("wlan") } -> "wifi"
            matching.any { it.name.startsWith("eth") } -> "wired"
            else -> "local"
        }
    }
    fun order(addresses:List<String>,subnets:List<ImportSubnet>)=addresses.distinct().filter(::isPrivate)
        .sortedBy { when(transport(it,subnets)) { "usb"->0; "wired"->1; "wifi"->2; else->3 } }
}
